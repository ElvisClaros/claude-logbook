package main

// The server never accepts HTML: it takes the same JSON `claude-logbook
// --json -s` prints, checks its shape and builds the page itself from the
// CLI's own template. The only scripts that run under this domain are the
// template's, and the CSP pins them by hash.

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

const dataMarker = "__DATA__"

// ──────────────────────────────── validation ─────────────────────────────

type Block struct {
	R string `json:"r"`
	X string `json:"x"`
}

// Session mirrors a record of sessions.py without its internal keys.
// Pointers are the keys that may be null.
type Session struct {
	ID string   `json:"id"`
	P  string   `json:"p"`
	B  *string  `json:"b"`
	T  *string  `json:"t"`
	AI bool     `json:"ai"`
	N  bool     `json:"n"`
	E  bool     `json:"e"`
	I  bool     `json:"i"`
	F  *string  `json:"f"`
	L  *string  `json:"l"`
	D  *float64 `json:"d"`
	U  int      `json:"u"`
	A  int      `json:"a"`
	K  float64  `json:"k"`
	V  *string  `json:"v"`
	C  []Block  `json:"c"`
}

type Payload struct {
	S []Session         `json:"s"`
	M []json.RawMessage `json:"m"`
}

var sessionIDRE = regexp.MustCompile(`^[0-9a-zA-Z-]{1,64}$`)

// ParsePayload checks that raw has exactly the shape the template reads and
// returns it re-encoded, so nothing the server does not know travels on.
func ParsePayload(raw []byte, maxSessions int) (*Payload, []byte, error) {
	// Keys the server does not know are dropped rather than refused: a newer
	// CLI may add one, and re-encoding below leaves only what is listed here.
	dec := json.NewDecoder(bytes.NewReader(raw))
	var p Payload
	if err := dec.Decode(&p); err != nil {
		return nil, nil, fmt.Errorf("payload: %v", err)
	}
	if dec.More() {
		return nil, nil, errors.New("payload: trailing data")
	}
	if len(p.S) == 0 || len(p.S) > maxSessions {
		return nil, nil, fmt.Errorf("payload: between 1 and %d sessions", maxSessions)
	}
	if len(p.M) != 0 {
		return nil, nil, errors.New("payload: memories are not shared")
	}
	for i, s := range p.S {
		if !sessionIDRE.MatchString(s.ID) {
			return nil, nil, fmt.Errorf("payload: session %d: bad id", i)
		}
		if s.C == nil {
			return nil, nil, fmt.Errorf("payload: session %d: no c", i)
		}
		for j, b := range s.C {
			if b.R != "u" && b.R != "a" && b.R != "t" {
				return nil, nil, fmt.Errorf("payload: session %d block %d: bad r", i, j)
			}
		}
	}
	p.M = []json.RawMessage{}
	clean, err := json.Marshal(p)
	return &p, clean, err
}

// ──────────────────────────────── html ───────────────────────────────────

type Page struct {
	before, after string
	csp           string
}

var scriptRE = regexp.MustCompile(`(?s)<script([^>]*)>(.*?)</script>`)

// NewPage splits the template at its single marker and computes the CSP that
// allows exactly its inline scripts.
func NewPage(template string) (*Page, error) {
	if n := strings.Count(template, dataMarker); n != 1 {
		return nil, fmt.Errorf("template must contain exactly one %s (found %d)", dataMarker, n)
	}
	var hashes []string
	for _, m := range scriptRE.FindAllStringSubmatch(template, -1) {
		if strings.Contains(m[1], "application/json") {
			continue // data, not code: CSP does not apply to it
		}
		sum := sha256.Sum256([]byte(m[2]))
		hashes = append(hashes, "'sha256-"+base64.StdEncoding.EncodeToString(sum[:])+"'")
	}
	if len(hashes) == 0 {
		return nil, errors.New("template has no scripts")
	}
	before, after, _ := strings.Cut(template, dataMarker)
	csp := "default-src 'none'; script-src " + strings.Join(hashes, " ") +
		"; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; " +
		"form-action 'none'; frame-ancestors 'none'"
	return &Page{before: before, after: after, csp: csp}, nil
}

// EncodeData does what encode_payload in webpage.py does: the HTML parser
// ends a <script> at the first "</", so it is written as "<\/", a JSON escape
// that JSON.parse turns back into "</". Go already escapes <, > and & as
// <..., which covers "<!--" too.
func EncodeData(clean []byte) []byte {
	return bytes.ReplaceAll(clean, []byte("</"), []byte(`<\/`))
}

func (pg *Page) Render(clean []byte) []byte {
	var b bytes.Buffer
	b.WriteString(pg.before)
	b.Write(EncodeData(clean))
	b.WriteString(pg.after)
	return b.Bytes()
}

// ──────────────────────────────── text ───────────────────────────────────

func deref(s *string, alt string) string {
	if s == nil || *s == "" {
		return alt
	}
	return *s
}

func fmtStamp(s *string) string {
	if s == nil {
		return "?"
	}
	t, err := time.Parse(time.RFC3339, *s)
	if err != nil {
		return *s
	}
	return t.UTC().Format("2006-01-02 15:04 UTC")
}

// RenderText is the transcript in plain text, in the order the terminal
// shows it with `claude-logbook -s`.
func RenderText(p *Payload) []byte {
	var b strings.Builder
	for i, s := range p.S {
		if i > 0 {
			b.WriteString("\n\n")
		}
		title := deref(s.T, "Untitled session")
		fmt.Fprintf(&b, "# %s\n\n", title)
		fmt.Fprintf(&b, "project:  %s\n", s.P)
		if s.B != nil && *s.B != "" {
			fmt.Fprintf(&b, "branch:   %s\n", *s.B)
		}
		fmt.Fprintf(&b, "from:     %s\nto:       %s\n", fmtStamp(s.F), fmtStamp(s.L))
		fmt.Fprintf(&b, "messages: %d yours / %d from Claude\n", s.U, s.A)
		if s.V != nil && *s.V != "" {
			fmt.Fprintf(&b, "version:  Claude Code %s\n", *s.V)
		}
		fmt.Fprintf(&b, "session:  %s\n", s.ID)
		if len(s.C) == 0 {
			b.WriteString("\nThis session has no messages.\n")
			continue
		}
		prev := ""
		for _, c := range s.C {
			switch c.R {
			case "t":
				if prev != "t" {
					b.WriteString("\n")
				}
				fmt.Fprintf(&b, "> tool: %s\n", strings.ReplaceAll(c.X, "\n", " "))
			default:
				who := "User"
				if c.R == "a" {
					who = "Claude"
				}
				fmt.Fprintf(&b, "\n## %s\n\n%s\n", who, strings.TrimRight(c.X, "\n"))
			}
			prev = c.R
		}
	}
	return []byte(b.String())
}
