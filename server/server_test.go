package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const session = `{"id":"aaaaaaaa-0000-0000-0000-000000000001","p":"/home/u/proj","b":"main",
"t":"Fix the build","ai":true,"n":false,"e":false,"i":false,"f":"2025-08-14T10:00:00.000Z",
"l":"2025-08-14T10:05:00.000Z","d":5,"u":1,"a":1,"k":1.5,"v":"1.0.0",
"c":[{"r":"u","x":"why does the build fail?"},{"r":"t","x":"Bash: make"},
{"r":"a","x":"A missing </script><script>alert(1)</script> tag."}]}`

func payload(sessions ...string) string {
	if len(sessions) == 0 {
		sessions = []string{session}
	}
	return `{"s":[` + strings.Join(sessions, ",") + `],"m":[]}`
}

type harness struct {
	t   *testing.T
	srv *Server
	h   http.Handler
}

func newHarness(t *testing.T, mod func(*Config)) *harness {
	t.Helper()
	cfg := Config{Addr: ":0", DataDir: t.TempDir(), PublicURL: "https://x.test",
		MaxBytes: 1 << 20, MaxSessions: 1, TrustedProxy: "10.0.0.1",
		CreatesPerH: 100, WritesPerH: 100}
	if mod != nil {
		mod(&cfg)
	}
	srv, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return &harness{t: t, srv: srv, h: srv.Routes()}
}

func (h *harness) do(method, path, body, secret string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.RemoteAddr = "192.0.2.1:1234"
	if secret != "" {
		req.Header.Set("Authorization", "Bearer "+secret)
	}
	rec := httptest.NewRecorder()
	h.h.ServeHTTP(rec, req)
	return rec
}

func (h *harness) create(body string) shareResp {
	h.t.Helper()
	rec := h.do("POST", "/api/shares", body, "")
	if rec.Code != http.StatusCreated {
		h.t.Fatalf("create: %d %s", rec.Code, rec.Body)
	}
	var r shareResp
	if err := json.Unmarshal(rec.Body.Bytes(), &r); err != nil {
		h.t.Fatal(err)
	}
	return r
}

func TestCreateAndRead(t *testing.T) {
	h := newHarness(t, nil)
	r := h.create(`{"payload":` + payload() + `,"expire":"7d"}`)
	if !ValidID(r.ID) || r.Secret == "" || r.URL != "https://x.test/share/"+r.ID {
		t.Fatalf("bad response %+v", r)
	}
	if d := time.Until(r.Expires); d < 6*24*time.Hour || d > 8*24*time.Hour {
		t.Fatalf("expiry %v", r.Expires)
	}

	page := h.do("GET", "/share/"+r.ID, "", "")
	if page.Code != 200 || !strings.Contains(page.Header().Get("Content-Type"), "text/html") {
		t.Fatalf("html: %d", page.Code)
	}
	csp := page.Header().Get("Content-Security-Policy")
	if !strings.Contains(csp, "script-src 'sha256-") || strings.Contains(csp, "unsafe-inline' ;") {
		t.Fatalf("csp: %s", csp)
	}
	if page.Header().Get("X-Robots-Tag") == "" {
		t.Fatal("no X-Robots-Tag")
	}
	body := page.Body.String()
	// The data block must hold exactly one </script>: its own end.
	start := strings.Index(body, `<script id="payload" type="application/json">`)
	end := strings.Index(body[start:], "</script>")
	if strings.Contains(body[start:start+end], "<script>alert") || !strings.Contains(body[start:start+end], "Fix the build") {
		t.Fatal("payload escaped wrong")
	}

	txt := h.do("GET", "/share/"+r.ID+".txt", "", "")
	want := []string{"# Fix the build", "project:  /home/u/proj", "## User",
		"why does the build fail?", "> tool: Bash: make", "## Claude"}
	for _, w := range want {
		if !strings.Contains(txt.Body.String(), w) {
			t.Fatalf("txt lacks %q:\n%s", w, txt.Body)
		}
	}

	js := h.do("GET", "/share/"+r.ID+".json", "", "")
	var p Payload
	if err := json.Unmarshal(js.Body.Bytes(), &p); err != nil || p.S[0].C[2].X != "A missing </script><script>alert(1)</script> tag." {
		t.Fatalf("json roundtrip: %v %s", err, js.Body)
	}

	if rec := h.do("GET", "/share/"+r.ID+".pdf", "", ""); rec.Code != 404 {
		t.Fatalf("unknown extension: %d", rec.Code)
	}
}

func TestCompactionBlock(t *testing.T) {
	h := newHarness(t, nil)
	withC := strings.Replace(session, `"c":[`, `"c":[{"r":"c","x":"earlier summary"},`, 1)
	r := h.create(`{"payload":` + payload(withC) + `}`)
	txt := h.do("GET", "/share/"+r.ID+".txt", "", "").Body.String()
	if !strings.Contains(txt, "--- context compacted here ---") || strings.Contains(txt, "earlier summary") {
		t.Fatalf("txt: %s", txt)
	}
}

func TestBranchAndDirectoryChange(t *testing.T) {
	h := newHarness(t, nil)
	branch := strings.Replace(session, `"c":[`, `"h":1,"o":"bbbbbbbb-0000","ot":"The original",`+
		`"c":[{"r":"u","x":"old question"},{"r":"d","x":"/home/u/proj/sub"},`, 1)
	r := h.create(`{"payload":` + payload(branch) + `}`)
	txt := h.do("GET", "/share/"+r.ID+".txt", "", "").Body.String()
	for _, want := range []string{"--- inherited history, from The original ---\n\n## User\n\nold question",
		"--- the branch starts here ---\n\n> cd: /home/u/proj/sub\n"} {
		if !strings.Contains(txt, want) {
			t.Fatalf("missing %q in txt: %s", want, txt)
		}
	}
	js := h.do("GET", "/share/"+r.ID+".json", "", "").Body.String()
	if !strings.Contains(js, `"h":1,"o":"bbbbbbbb-0000","ot":"The original"`) {
		t.Fatalf("json: %s", js)
	}
}

func TestImages(t *testing.T) {
	h := newHarness(t, nil)
	png := "data:image/png;base64," + base64.StdEncoding.EncodeToString([]byte("\x89PNG\r\n\x1a\nrest"))
	withImg := strings.Replace(session, `"c":[`, `"c":[{"r":"i","x":"[image]","src":"`+png+`"},{"r":"v","x":"[image]"},`, 1)
	r := h.create(`{"payload":` + payload(withImg) + `}`)
	if js := h.do("GET", "/share/"+r.ID+".json", "", "").Body.String(); !strings.Contains(js, png) {
		t.Fatalf("image lost: %s", js)
	}
	txt := h.do("GET", "/share/"+r.ID+".txt", "", "").Body.String()
	if !strings.Contains(txt, "> image attached\n> image from the tool\n") {
		t.Fatalf("txt: %s", txt)
	}

	svg := "data:image/svg+xml;base64," + base64.StdEncoding.EncodeToString([]byte("<svg onload=alert(1)>"))
	fake := "data:image/png;base64," + base64.StdEncoding.EncodeToString([]byte("<script>"))
	for name, block := range map[string]string{
		"svg":           `{"r":"i","x":"","src":"` + svg + `"}`,
		"wrong bytes":   `{"r":"i","x":"","src":"` + fake + `"}`,
		"not base64":    `{"r":"i","x":"","src":"data:image/png;base64,%%%"}`,
		"remote":        `{"r":"i","x":"","src":"https://evil.test/x.png"}`,
		"src on a text": `{"r":"u","x":"","src":"` + png + `"}`,
	} {
		bad := strings.Replace(session, `"c":[`, `"c":[`+block+`,`, 1)
		if rec := h.do("POST", "/api/shares", `{"payload":`+payload(bad)+`}`, ""); rec.Code != 400 {
			t.Errorf("%s: %d %s", name, rec.Code, rec.Body)
		}
	}
}

func TestUpdateAndDeleteNeedTheSecret(t *testing.T) {
	h := newHarness(t, nil)
	r := h.create(`{"payload":` + payload() + `}`)
	newer := strings.Replace(payload(), "Fix the build", "Fixed the build", 1)

	if rec := h.do("PUT", "/api/shares/"+r.ID, `{"payload":`+newer+`}`, ""); rec.Code != 401 {
		t.Fatalf("no secret: %d", rec.Code)
	}
	if rec := h.do("PUT", "/api/shares/"+r.ID, `{"payload":`+newer+`}`, "nope"); rec.Code != 403 {
		t.Fatalf("wrong secret: %d", rec.Code)
	}
	if rec := h.do("PUT", "/api/shares/"+r.ID, `{"payload":`+newer+`}`, r.Secret); rec.Code != 200 {
		t.Fatalf("update: %d %s", rec.Code, rec.Body)
	}
	if !strings.Contains(h.do("GET", "/share/"+r.ID+".txt", "", "").Body.String(), "Fixed the build") {
		t.Fatal("update not visible")
	}
	if rec := h.do("DELETE", "/api/shares/"+r.ID, "", "nope"); rec.Code != 403 {
		t.Fatalf("delete wrong secret: %d", rec.Code)
	}
	if rec := h.do("DELETE", "/api/shares/"+r.ID, "", r.Secret); rec.Code != 204 {
		t.Fatalf("delete: %d", rec.Code)
	}
	if rec := h.do("GET", "/share/"+r.ID, "", ""); rec.Code != 404 {
		t.Fatalf("after delete: %d", rec.Code)
	}
	if rec := h.do("DELETE", "/api/shares/"+r.ID, "", r.Secret); rec.Code != 404 {
		t.Fatalf("delete twice: %d", rec.Code)
	}
}

func TestExpiry(t *testing.T) {
	h := newHarness(t, nil)
	r := h.create(`{"payload":` + payload() + `,"expire":"1d"}`)
	h.srv.store.now = func() time.Time { return time.Now().Add(25 * time.Hour) }
	if rec := h.do("GET", "/share/"+r.ID, "", ""); rec.Code != 404 {
		t.Fatalf("expired share served: %d", rec.Code)
	}
	if n := h.srv.store.Sweep(); n != 1 {
		t.Fatalf("swept %d", n)
	}
}

func TestNotFound(t *testing.T) {
	h := newHarness(t, nil)
	for _, p := range []string{"/share/AAAAAAAAAA", "/share/..%2Fetc%2Fpasswd", "/share/x", "/nope"} {
		if rec := h.do("GET", p, "", ""); rec.Code != 404 {
			t.Fatalf("%s: %d", p, rec.Code)
		}
	}
}

func TestRejectsBadPayloads(t *testing.T) {
	h := newHarness(t, nil)
	bad := map[string]string{
		"html":         `{"payload":"<html><script>alert(1)</script>"}`,
		"no sessions":  `{"payload":{"s":[],"m":[]}}`,
		"two sessions": `{"payload":` + payload(session, session) + `}`,
		"bad role":     `{"payload":` + payload(strings.Replace(session, `"r":"t"`, `"r":"z"`, 1)) + `}`,
		"bad type":     `{"payload":` + payload(strings.Replace(session, `"u":1`, `"u":"1"`, 1)) + `}`,
		"h too big":    `{"payload":` + payload(strings.Replace(session, `"c":[`, `"h":9,"c":[`, 1)) + `}`,
		"bad origin":   `{"payload":` + payload(strings.Replace(session, `"c":[`, `"o":"../x","c":[`, 1)) + `}`,
		"memories":     `{"payload":{"s":[` + session + `],"m":[{"name":"x"}]}}`,
		"bad expire":   `{"payload":` + payload() + `,"expire":"never"}`,
		"extra field":  `{"payload":` + payload() + `,"html":"x"}`,
		"no payload":   `{"expire":"1d"}`,
		"not json":     `hello`,
	}
	for name, body := range bad {
		if rec := h.do("POST", "/api/shares", body, ""); rec.Code != 400 {
			t.Errorf("%s: %d %s", name, rec.Code, rec.Body)
		}
	}
}

func TestUnknownKeysAreDropped(t *testing.T) {
	h := newHarness(t, nil)
	evil := strings.Replace(session, `"ai":true`, `"ai":true,"evil":"<x>"`, 1)
	r := h.create(`{"payload":{"s":[` + evil + `],"m":[],"x":1}}`)
	js := h.do("GET", "/share/"+r.ID+".json", "", "").Body.String()
	if strings.Contains(js, "evil") || strings.Contains(js, `"x":1`) {
		t.Fatalf("unknown keys kept: %s", js)
	}
}

func TestTooLarge(t *testing.T) {
	h := newHarness(t, func(c *Config) { c.MaxBytes = 512 })
	big := payload(strings.Replace(session, "why does", strings.Repeat("x", 1000), 1))
	if rec := h.do("POST", "/api/shares", `{"payload":`+big+`}`, ""); rec.Code != 413 {
		t.Fatalf("too large: %d %s", rec.Code, rec.Body)
	}
}

func TestRateLimit(t *testing.T) {
	h := newHarness(t, func(c *Config) { c.CreatesPerH = 2 })
	body := `{"payload":` + payload() + `}`
	h.create(body)
	h.create(body)
	if rec := h.do("POST", "/api/shares", body, ""); rec.Code != 429 {
		t.Fatalf("third create: %d", rec.Code)
	}
}

func TestClientIP(t *testing.T) {
	c, err := NewClientIP("10.0.0.1, 172.16.0.0/12")
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct{ remote, xff, want string }{
		{"192.0.2.1:1", "203.0.113.9", "192.0.2.1"},              // not the proxy: header ignored
		{"10.0.0.1:1", "203.0.113.9", "203.0.113.9"},             // the proxy
		{"10.0.0.1:1", "6.6.6.6, 203.0.113.9", "203.0.113.9"},    // client forged the left part
		{"172.20.0.5:1", "203.0.113.9, 10.0.0.1", "203.0.113.9"}, // chain of proxies
		{"10.0.0.1:1", "", "10.0.0.1"},
	}
	for _, tc := range cases {
		r := httptest.NewRequest("GET", "/", nil)
		r.RemoteAddr = tc.remote
		if tc.xff != "" {
			r.Header.Set("X-Forwarded-For", tc.xff)
		}
		if got := c.Of(r); got != tc.want {
			t.Errorf("%s %q: got %s want %s", tc.remote, tc.xff, got, tc.want)
		}
	}
}

func TestHome(t *testing.T) {
	h := newHarness(t, nil)
	rec := h.do("GET", "/", "", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "https://x.test/share/&lt;id&gt;.txt") {
		t.Fatalf("home: %d", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "{{") {
		t.Fatal("placeholder left")
	}
	if rec := h.do("GET", "/healthz", "", ""); rec.Code != 200 {
		t.Fatalf("healthz: %d", rec.Code)
	}
}

func TestStoredFilesArePrivate(t *testing.T) {
	h := newHarness(t, nil)
	r := h.create(`{"payload":` + payload() + `}`)
	raw, meta, err := h.srv.store.Get(r.ID)
	if err != nil || len(raw) == 0 {
		t.Fatal(err)
	}
	if meta.SecretHash == r.Secret || !bytes.Equal([]byte(meta.SecretHash), []byte(hashOf(r.Secret))) {
		t.Fatal("secret must be stored hashed")
	}
}
