// Command server publishes claude-logbook sessions at /share/<id>.
//
// Anyone may create a share (that is what `claude-logbook --share` does);
// only whoever holds the secret returned on creation may replace or delete
// it. Abuse is held back by size limits, payload validation and a rate limit
// per client IP.
package main

import (
	_ "embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

//go:generate cp ../claude_logbook/template.html template.html

//go:embed template.html
var templateHTML string

//go:embed home.html
var homeHTML string

// TTLs the client may ask for; the first is the default.
var ttls = map[string]time.Duration{
	"1d": 24 * time.Hour, "7d": 7 * 24 * time.Hour,
	"30d": 30 * 24 * time.Hour, "90d": 90 * 24 * time.Hour,
}

const defaultTTL = "30d"

type Config struct {
	Addr         string
	DataDir      string
	PublicURL    string
	MaxBytes     int64
	MaxSessions  int
	TrustedProxy string
	CreatesPerH  int
	WritesPerH   int
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
		log.Fatalf("%s: not a number: %q", key, v)
	}
	return def
}

type Server struct {
	cfg     Config
	store   *Store
	page    *Page
	ip      *ClientIP
	creates *Limiter
	writes  *Limiter
	home    []byte
}

func NewServer(cfg Config) (*Server, error) {
	store, err := NewStore(cfg.DataDir)
	if err != nil {
		return nil, err
	}
	page, err := NewPage(templateHTML)
	if err != nil {
		return nil, err
	}
	ip, err := NewClientIP(cfg.TrustedProxy)
	if err != nil {
		return nil, fmt.Errorf("TRUSTED_PROXY: %v", err)
	}
	home := strings.ReplaceAll(homeHTML, "{{PUBLIC_URL}}", cfg.PublicURL)
	return &Server{cfg: cfg, store: store, page: page, ip: ip,
		creates: NewLimiter(cfg.CreatesPerH, time.Hour),
		writes:  NewLimiter(cfg.WritesPerH, time.Hour),
		home:    []byte(home)}, nil
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", s.handleHome)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.Write([]byte("ok\n"))
	})
	mux.HandleFunc("GET /share/{name}", s.handleShare)
	mux.HandleFunc("POST /api/shares", s.handleCreate)
	mux.HandleFunc("PUT /api/shares/{id}", s.handleUpdate)
	mux.HandleFunc("DELETE /api/shares/{id}", s.handleDelete)
	return logRequests(securityHeaders(mux))
}

// ──────────────────────────────── pages ──────────────────────────────────

func (s *Server) handleHome(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Content-Security-Policy",
		"default-src 'none'; style-src 'unsafe-inline'; img-src data:; "+
			"base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
	w.Header().Set("Cache-Control", "public, max-age=300")
	w.Write(s.home)
}

func (s *Server) handleShare(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	id, ext, _ := strings.Cut(name, ".")
	raw, _, err := s.store.Get(id)
	if errors.Is(err, ErrNotFound) {
		http.Error(w, "share not found (it may have expired or been deleted)", http.StatusNotFound)
		return
	}
	if err != nil {
		s.fail(w, err)
		return
	}
	h := w.Header()
	h.Set("Cache-Control", "private, no-cache")
	h.Set("X-Robots-Tag", "noindex, nofollow")
	switch ext {
	case "":
		h.Set("Content-Type", "text/html; charset=utf-8")
		h.Set("Content-Security-Policy", s.page.csp)
		w.Write(s.page.Render(raw))
	case "json":
		h.Set("Content-Type", "application/json; charset=utf-8")
		w.Write(raw)
	case "txt":
		p, _, err := ParsePayload(raw, 1<<30)
		if err != nil {
			s.fail(w, err)
			return
		}
		h.Set("Content-Type", "text/plain; charset=utf-8")
		w.Write(RenderText(p))
	default:
		http.NotFound(w, r)
	}
}

// ──────────────────────────────── api ────────────────────────────────────

type writeReq struct {
	Payload json.RawMessage `json:"payload"`
	Expire  string          `json:"expire"`
}

type shareResp struct {
	ID      string    `json:"id"`
	URL     string    `json:"url"`
	Secret  string    `json:"secret,omitempty"`
	Expires time.Time `json:"expires"`
}

func jsonError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func (s *Server) fail(w http.ResponseWriter, err error) {
	log.Printf("error: %v", err)
	jsonError(w, http.StatusInternalServerError, "internal error")
}

// readWrite decodes and validates a POST/PUT body. ok=false means the error
// response was already written.
func (s *Server) readWrite(w http.ResponseWriter, r *http.Request, needPayload bool) (clean []byte, ttl time.Duration, ok bool) {
	r.Body = http.MaxBytesReader(w, r.Body, s.cfg.MaxBytes)
	var req writeReq
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			jsonError(w, http.StatusRequestEntityTooLarge,
				fmt.Sprintf("payload larger than %d bytes", s.cfg.MaxBytes))
			return nil, 0, false
		}
		jsonError(w, http.StatusBadRequest, "body: "+err.Error())
		return nil, 0, false
	}
	if req.Expire != "" {
		var known bool
		if ttl, known = ttls[req.Expire]; !known {
			jsonError(w, http.StatusBadRequest, "expire: one of 1d, 7d, 30d, 90d")
			return nil, 0, false
		}
	}
	if len(req.Payload) == 0 {
		if needPayload {
			jsonError(w, http.StatusBadRequest, "payload: missing")
			return nil, 0, false
		}
		return nil, ttl, true
	}
	_, clean, err := ParsePayload(req.Payload, s.cfg.MaxSessions)
	if err != nil {
		jsonError(w, http.StatusBadRequest, err.Error())
		return nil, 0, false
	}
	return clean, ttl, true
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if t, ok := strings.CutPrefix(h, "Bearer "); ok {
		return strings.TrimSpace(t)
	}
	return ""
}

func (s *Server) url(id string) string { return s.cfg.PublicURL + "/share/" + id }

func (s *Server) handleCreate(w http.ResponseWriter, r *http.Request) {
	ip := s.ip.Of(r)
	if !s.creates.Allow(ip) {
		w.Header().Set("Retry-After", "600")
		jsonError(w, http.StatusTooManyRequests, "too many shares from this address; try later")
		return
	}
	clean, ttl, ok := s.readWrite(w, r, true)
	if !ok {
		return
	}
	if ttl == 0 {
		ttl = ttls[defaultTTL]
	}
	id, secret, meta, err := s.store.Create(clean, ttl, ip)
	if err != nil {
		s.fail(w, err)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Location", "/share/"+id)
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(shareResp{ID: id, URL: s.url(id), Secret: secret, Expires: meta.Expires})
}

func (s *Server) authError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		jsonError(w, http.StatusNotFound, "share not found")
	case errors.Is(err, ErrDenied):
		jsonError(w, http.StatusForbidden, "wrong secret")
	default:
		s.fail(w, err)
	}
}

func (s *Server) writeAllowed(w http.ResponseWriter, r *http.Request) (string, bool) {
	if !s.writes.Allow(s.ip.Of(r)) {
		w.Header().Set("Retry-After", "60")
		jsonError(w, http.StatusTooManyRequests, "too many requests; try later")
		return "", false
	}
	secret := bearer(r)
	if secret == "" {
		jsonError(w, http.StatusUnauthorized, "missing Authorization: Bearer <secret>")
		return "", false
	}
	return secret, true
}

func (s *Server) handleUpdate(w http.ResponseWriter, r *http.Request) {
	secret, ok := s.writeAllowed(w, r)
	if !ok {
		return
	}
	clean, ttl, ok := s.readWrite(w, r, true)
	if !ok {
		return
	}
	id := r.PathValue("id")
	meta, err := s.store.Update(id, secret, clean, ttl)
	if err != nil {
		s.authError(w, err)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(shareResp{ID: id, URL: s.url(id), Expires: meta.Expires})
}

func (s *Server) handleDelete(w http.ResponseWriter, r *http.Request) {
	secret, ok := s.writeAllowed(w, r)
	if !ok {
		return
	}
	if err := s.store.Delete(r.PathValue("id"), secret); err != nil {
		s.authError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ──────────────────────────────── middleware ─────────────────────────────

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Cross-Origin-Opener-Policy", "same-origin")
		next.ServeHTTP(w, r)
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (sw *statusWriter) WriteHeader(code int) {
	sw.status = code
	sw.ResponseWriter.WriteHeader(code)
}

func (sw *statusWriter) Write(b []byte) (int, error) {
	if sw.status == 0 {
		sw.status = http.StatusOK
	}
	n, err := sw.ResponseWriter.Write(b)
	sw.bytes += n
	return n, err
}

// logRequests logs method, path, status and size; never bodies or headers,
// which carry transcripts and secrets.
func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w}
		next.ServeHTTP(sw, r)
		if r.URL.Path == "/healthz" {
			return
		}
		log.Printf("%s %s %d %dB %s", r.Method, r.URL.Path, sw.status, sw.bytes,
			time.Since(start).Round(time.Millisecond))
	})
}

// ──────────────────────────────── main ───────────────────────────────────

func (s *Server) janitor(every time.Duration) {
	for range time.Tick(every) {
		if n := s.store.Sweep(); n > 0 {
			log.Printf("swept %d expired shares", n)
		}
		s.creates.Prune()
		s.writes.Prune()
	}
}

func healthcheck(addr string) int {
	if strings.HasPrefix(addr, ":") {
		addr = "127.0.0.1" + addr
	}
	c := http.Client{Timeout: 3 * time.Second}
	resp, err := c.Get("http://" + addr + "/healthz")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}

func main() {
	cfg := Config{}
	flag.StringVar(&cfg.Addr, "addr", env("ADDR", ":8181"), "listen address")
	flag.StringVar(&cfg.DataDir, "data", env("DATA_DIR", "/data"), "where shares are stored")
	flag.StringVar(&cfg.PublicURL, "public-url", env("PUBLIC_URL", "https://claude-logbook.all.ar"), "base of the URLs handed out")
	flag.Int64Var(&cfg.MaxBytes, "max-bytes", envInt("MAX_BYTES", 20<<20), "largest request body")
	maxSessions := flag.Int64("max-sessions", envInt("MAX_SESSIONS", 1), "sessions per share")
	flag.StringVar(&cfg.TrustedProxy, "trusted-proxy", env("TRUSTED_PROXY", ""), "IPs/CIDRs whose X-Forwarded-For is believed (comma separated)")
	creates := flag.Int64("creates-per-hour", envInt("CREATES_PER_HOUR", 10), "new shares per IP and hour")
	writes := flag.Int64("writes-per-hour", envInt("WRITES_PER_HOUR", 60), "updates and deletes per IP and hour")
	check := flag.Bool("healthcheck", false, "query /healthz and exit (for Docker HEALTHCHECK)")
	flag.Parse()
	cfg.MaxSessions, cfg.CreatesPerH, cfg.WritesPerH = int(*maxSessions), int(*creates), int(*writes)
	cfg.PublicURL = strings.TrimRight(cfg.PublicURL, "/")

	if *check {
		os.Exit(healthcheck(cfg.Addr))
	}

	srv, err := NewServer(cfg)
	if err != nil {
		log.Fatal(err)
	}
	if cfg.TrustedProxy == "" {
		log.Printf("TRUSTED_PROXY is empty: X-Forwarded-For is ignored and the " +
			"rate limit counts the proxy's address, not the client's")
	}
	srv.store.Sweep()
	go srv.janitor(time.Hour)

	hs := &http.Server{
		Addr:              cfg.Addr,
		Handler:           srv.Routes(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       180 * time.Second, // 20 MB of images on a slow uplink
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       120 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	log.Printf("listening on %s, data in %s, public URL %s", cfg.Addr, cfg.DataDir, cfg.PublicURL)
	log.Fatal(hs.ListenAndServe())
}
