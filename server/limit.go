package main

import (
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

// Limiter is a token bucket per key (the client IP): `burst` requests at
// once, refilled at `burst` per `per`. In memory: a restart forgets it.
type Limiter struct {
	burst   float64
	rate    float64 // tokens per second
	mu      sync.Mutex
	buckets map[string]*bucket
	now     func() time.Time
}

type bucket struct {
	tokens float64
	last   time.Time
}

func NewLimiter(burst int, per time.Duration) *Limiter {
	return &Limiter{burst: float64(burst), rate: float64(burst) / per.Seconds(),
		buckets: map[string]*bucket{}, now: time.Now}
}

func (l *Limiter) Allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	b, ok := l.buckets[key]
	if !ok {
		b = &bucket{tokens: l.burst, last: now}
		l.buckets[key] = b
	}
	b.tokens += now.Sub(b.last).Seconds() * l.rate
	if b.tokens > l.burst {
		b.tokens = l.burst
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// Prune drops the buckets that are full again: they behave as new ones.
func (l *Limiter) Prune() {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	for k, b := range l.buckets {
		if b.tokens+now.Sub(b.last).Seconds()*l.rate >= l.burst {
			delete(l.buckets, k)
		}
	}
}

// ClientIP trusts X-Forwarded-For only when the connection comes from the
// proxy (Nginx Proxy Manager); anyone else could write that header.
type ClientIP struct {
	trusted []*net.IPNet
}

func NewClientIP(spec string) (*ClientIP, error) {
	c := &ClientIP{}
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if !strings.Contains(part, "/") {
			if strings.Contains(part, ":") {
				part += "/128"
			} else {
				part += "/32"
			}
		}
		_, n, err := net.ParseCIDR(part)
		if err != nil {
			return nil, err
		}
		c.trusted = append(c.trusted, n)
	}
	return c, nil
}

func (c *ClientIP) isTrusted(ip net.IP) bool {
	for _, n := range c.trusted {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

func (c *ClientIP) Of(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer := net.ParseIP(host)
	if peer == nil || !c.isTrusted(peer) {
		return host
	}
	// Rightmost address that is not a trusted proxy: what the client put
	// further left could be invented.
	hops := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
	for i := len(hops) - 1; i >= 0; i-- {
		ip := net.ParseIP(strings.TrimSpace(hops[i]))
		if ip == nil {
			break
		}
		if !c.isTrusted(ip) {
			return ip.String()
		}
	}
	if real := net.ParseIP(strings.TrimSpace(r.Header.Get("X-Real-IP"))); real != nil {
		return real.String()
	}
	return host
}
