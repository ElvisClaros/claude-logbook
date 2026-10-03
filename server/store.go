package main

// Shares live as two files in the data directory:
//
//	<id>.json   the payload exactly as it was uploaded
//	<id>.meta   who may change it and until when it lives
//
// No database: the binary stays static and fits in a scratch image. Every
// write goes to a temporary file that is then renamed over the old one.

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const idLen = 10

var (
	idRE        = regexp.MustCompile(`^[0-9A-Za-z]{10}$`)
	ErrNotFound = errors.New("not found")
	ErrDenied   = errors.New("wrong secret")
)

const base62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

type Meta struct {
	SecretHash string    `json:"secret_hash"`
	Created    time.Time `json:"created"`
	Updated    time.Time `json:"updated"`
	Expires    time.Time `json:"expires"`
	IPHash     string    `json:"ip_hash"`
}

type Store struct {
	dir string
	mu  sync.Mutex // serializes writes; reads go straight to disk
	now func() time.Time
}

func NewStore(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	return &Store{dir: dir, now: func() time.Time { return time.Now().UTC() }}, nil
}

func ValidID(id string) bool { return idRE.MatchString(id) }

func newID() (string, error) {
	var b strings.Builder
	max := big.NewInt(int64(len(base62)))
	for i := 0; i < idLen; i++ {
		n, err := rand.Int(rand.Reader, max)
		if err != nil {
			return "", err
		}
		b.WriteByte(base62[n.Int64()])
	}
	return b.String(), nil
}

func newSecret() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

func hashOf(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

func (s *Store) path(id, ext string) string { return filepath.Join(s.dir, id+ext) }

func writeAtomic(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".tmp-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name()) // no-op once renamed
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

func (s *Store) readMeta(id string) (Meta, error) {
	var m Meta
	raw, err := os.ReadFile(s.path(id, ".meta"))
	if errors.Is(err, os.ErrNotExist) {
		return m, ErrNotFound
	}
	if err != nil {
		return m, err
	}
	if err := json.Unmarshal(raw, &m); err != nil {
		return m, err
	}
	if !s.now().Before(m.Expires) {
		return m, ErrNotFound
	}
	return m, nil
}

func (s *Store) writeMeta(id string, m Meta) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	return writeAtomic(s.path(id, ".meta"), raw)
}

// Create stores a new share and returns its id and secret. The secret is
// only ever kept hashed.
func (s *Store) Create(payload []byte, ttl time.Duration, ip string) (string, string, Meta, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	secret, err := newSecret()
	if err != nil {
		return "", "", Meta{}, err
	}
	for {
		id, err := newID()
		if err != nil {
			return "", "", Meta{}, err
		}
		if _, err := os.Stat(s.path(id, ".meta")); err == nil {
			continue // taken, even if expired and not swept yet
		}
		now := s.now()
		m := Meta{SecretHash: hashOf(secret), Created: now, Updated: now,
			Expires: now.Add(ttl), IPHash: hashOf(ip)}
		// Payload first: a meta without payload would be a share that 500s.
		if err := writeAtomic(s.path(id, ".json"), payload); err != nil {
			return "", "", Meta{}, err
		}
		if err := s.writeMeta(id, m); err != nil {
			os.Remove(s.path(id, ".json"))
			return "", "", Meta{}, err
		}
		return id, secret, m, nil
	}
}

// Get returns the payload of a live share.
func (s *Store) Get(id string) ([]byte, Meta, error) {
	if !ValidID(id) {
		return nil, Meta{}, ErrNotFound
	}
	m, err := s.readMeta(id)
	if err != nil {
		return nil, m, err
	}
	raw, err := os.ReadFile(s.path(id, ".json"))
	if errors.Is(err, os.ErrNotExist) {
		return nil, m, ErrNotFound
	}
	return raw, m, err
}

func (s *Store) authorize(id, secret string) (Meta, error) {
	if !ValidID(id) {
		return Meta{}, ErrNotFound
	}
	m, err := s.readMeta(id)
	if err != nil {
		return m, err
	}
	if subtle.ConstantTimeCompare([]byte(hashOf(secret)), []byte(m.SecretHash)) != 1 {
		return m, ErrDenied
	}
	return m, nil
}

// Update replaces the payload; ttl > 0 also restarts the expiry from now.
func (s *Store) Update(id, secret string, payload []byte, ttl time.Duration) (Meta, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m, err := s.authorize(id, secret)
	if err != nil {
		return m, err
	}
	if err := writeAtomic(s.path(id, ".json"), payload); err != nil {
		return m, err
	}
	m.Updated = s.now()
	if ttl > 0 {
		m.Expires = m.Updated.Add(ttl)
	}
	return m, s.writeMeta(id, m)
}

func (s *Store) Delete(id, secret string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.authorize(id, secret); err != nil {
		return err
	}
	s.remove(id)
	return nil
}

func (s *Store) remove(id string) {
	// Meta first: without it the share is already gone for readers.
	os.Remove(s.path(id, ".meta"))
	os.Remove(s.path(id, ".json"))
}

// Sweep deletes expired shares, payloads left without meta and stale
// temporary files. Returns how many shares it removed.
func (s *Store) Sweep() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return 0
	}
	now := s.now()
	removed := 0
	for _, e := range entries {
		name := e.Name()
		switch {
		case strings.HasPrefix(name, ".tmp-"):
			if info, err := e.Info(); err == nil && now.Sub(info.ModTime()) > time.Hour {
				os.Remove(filepath.Join(s.dir, name))
			}
		case strings.HasSuffix(name, ".meta"):
			id := strings.TrimSuffix(name, ".meta")
			if _, err := s.readMeta(id); errors.Is(err, ErrNotFound) {
				s.remove(id)
				removed++
			}
		case strings.HasSuffix(name, ".json"):
			id := strings.TrimSuffix(name, ".json")
			if _, err := os.Stat(s.path(id, ".meta")); errors.Is(err, os.ErrNotExist) {
				if info, err := e.Info(); err == nil && now.Sub(info.ModTime()) > time.Hour {
					os.Remove(filepath.Join(s.dir, name))
				}
			}
		}
	}
	return removed
}
