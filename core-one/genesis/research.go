package genesis

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	webResearchRequestTimeout = 5 * time.Second
	webResearchOverallTimeout = 13 * time.Second

	webResearchMaxQueryBytes    = 1000
	webResearchMaxResponseBytes = 1 << 20
	webResearchMaxSources       = 64
	webResearchMaxFindings      = 16
	webResearchMaxSourceTitle   = 300
	webResearchMaxSourceSnippet = 700
)

var allowedResearchAPIHosts = map[string]struct{}{
	"api.github.com":       {},
	"export.arxiv.org":     {},
	"services.nvd.nist.gov": {},
	"news.google.com":      {},
}

// WebResearcher uses Go's standard library. Downloaded content is parsed as
// data only and is never executed. Search links are distinguished from
// retrieved results and are not presented as independently verified claims.
type WebResearcher struct {
	Client  *http.Client
	Offline bool
}

func NewWebResearcher() *WebResearcher {
	offline := strings.EqualFold(strings.TrimSpace(os.Getenv("GENESIS_OFFLINE")), "1") ||
		strings.EqualFold(strings.TrimSpace(os.Getenv("GENESIS_OFFLINE")), "true")

	return &WebResearcher{
		Client:  &http.Client{Timeout: webResearchRequestTimeout},
		Offline: offline,
	}
}

// Research gathers bounded public research records. Online collectors run
// concurrently, but their results are merged in a stable collector order.
func (r *WebResearcher) Research(
	ctx context.Context,
	demand string,
) (ResearchEvidence, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return ResearchEvidence{}, err
	}

	query, err := normalizeResearchQuery(demand)
	if err != nil {
		return ResearchEvidence{}, err
	}

	now := time.Now().UTC()
	evidence := ResearchEvidence{
		ID:         newID("research"),
		Query:      query,
		CollectedAt: now,
		Mode:       "online-with-offline-fallback",
		Sources:    []ResearchSource{},
		Findings:   []string{},
	}

	if r == nil || r.Offline {
		evidence.Mode = "offline"
	}

	encodedQuery := url.QueryEscape(query)
	evidence.Sources = append(evidence.Sources, []ResearchSource{
		{
			Name:   "WIPO Patentscope search",
			URL:    "https://patentscope.wipo.int/search/en/search.jsf?query=" + encodedQuery,
			Status: "reference_link",
		},
		{
			Name:   "ISO standards search",
			URL:    "https://www.iso.org/search.html?q=" + encodedQuery,
			Status: "reference_link",
		},
		{
			Name:   "KEBS standards catalogue",
			URL:    "https://www.kebs.org/",
			Status: "reference_link",
		},
		{
			Name:   "Jumia Kenya product research",
			URL:    "https://www.jumia.co.ke/catalog/?q=" + encodedQuery,
			Status: "reference_link",
		},
		{
			Name:   "Mouser component research",
			URL:    "https://www.mouser.com/c/?q=" + encodedQuery,
			Status: "reference_link",
		},
		{
			Name:   "DigiKey semiconductor and component research",
			URL:    "https://www.digikey.com/en/products",
			Status: "reference_link",
		},
		{
			Name:   "Kenya demand and news search",
			URL:    "https://news.google.com/rss/search?q=" + url.QueryEscape(query+" Kenya demand") + "&hl=en-KE&gl=KE&ceid=KE:en",
			Status: "reference_link",
		},
	}...)

	if evidence.Mode != "offline" {
		researchCtx, cancel := context.WithTimeout(ctx, webResearchOverallTimeout)
		defer cancel()

		collectors := []func(context.Context, string) []ResearchSource{
			r.github,
			r.arxiv,
			r.nvd,
			r.kenyaRSS,
		}

		results := make([][]ResearchSource, len(collectors))

		var wg sync.WaitGroup
		for i, collector := range collectors {
			wg.Add(1)

			go func(index int, collect func(context.Context, string) []ResearchSource) {
				defer wg.Done()
				results[index] = collect(researchCtx, query)
			}(i, collector)
		}

		wg.Wait()

		if err := ctx.Err(); err != nil {
			return ResearchEvidence{}, err
		}

		for _, result := range results {
			evidence.Sources = append(evidence.Sources, result...)
		}
	} else {
		evidence.Findings = append(
			evidence.Findings,
			"Offline mode is enabled; network retrieval was not attempted.",
		)
	}

	if err := ctx.Err(); err != nil {
		return ResearchEvidence{}, err
	}

	evidence.Sources = deduplicateResearchSources(evidence.Sources, webResearchMaxSources)

	retrieved := 0
	referenceLinks := 0
	unavailable := 0

	for _, source := range evidence.Sources {
		switch source.Status {
		case "retrieved":
			retrieved++
		case "reference_link":
			referenceLinks++
		case "unavailable", "parse_error":
			unavailable++
		}
	}

	evidence.Findings = append(evidence.Findings,
		fmt.Sprintf(
			"Collected %d unique source records: %d retrieved records, %d reference links, and %d unavailable or unparseable records.",
			len(evidence.Sources),
			retrieved,
			referenceLinks,
			unavailable,
		),
		"Search links are research leads, not proof of current prices, regulatory compliance, patent clearance, supplier availability, or market demand.",
		"Retrieved descriptions are third-party information and remain unverified until independently reviewed.",
	)

	evidence.Findings = cleanResearchFindings(evidence.Findings, webResearchMaxFindings)
	return evidence, nil
}

func normalizeResearchQuery(raw string) (string, error) {
	if !utf8.ValidString(raw) {
		return "", errors.New("research query is not valid UTF-8")
	}

	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("research demand cannot be empty")
	}
	if len(raw) > webResearchMaxQueryBytes {
		return "", fmt.Errorf(
			"research demand exceeds the %d-byte limit",
			webResearchMaxQueryBytes,
		)
	}

	for _, r := range raw {
		if unicode.IsControl(r) && !unicode.IsSpace(r) {
			return "", errors.New("research demand contains invalid control characters")
		}
	}

	raw = strings.Join(strings.Fields(raw), " ")
	if raw == "" {
		return "", errors.New("research demand cannot be empty")
	}

	return raw, nil
}

// get retrieves data only from a specific allowlist of research APIs.
// Redirects are not followed, preventing a trusted API from redirecting the
// request to an unexpected host or internal network service.
func (r *WebResearcher) get(
	ctx context.Context,
	rawURL string,
) ([]byte, int, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, 0, err
	}

	parsedURL, err := validateResearchAPIURL(rawURL)
	if err != nil {
		return nil, 0, err
	}

	requestCtx, cancel := context.WithTimeout(ctx, webResearchRequestTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(
		requestCtx,
		http.MethodGet,
		parsedURL.String(),
		nil,
	)
	if err != nil {
		return nil, 0, fmt.Errorf("create research request: %w", err)
	}

	req.Header.Set(
		"User-Agent",
		"RevelaGenesis/"+Version+" (+https://github.com/musombi123/RevelaAI)",
	)
	req.Header.Set(
		"Accept",
		"application/json, application/atom+xml, application/rss+xml, application/xml, text/xml",
	)

	client := r.researchHTTPClient()
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(
		io.LimitReader(resp.Body, webResearchMaxResponseBytes+1),
	)
	if err != nil {
		return nil, resp.StatusCode, fmt.Errorf("read research response: %w", err)
	}

	if len(body) > webResearchMaxResponseBytes {
		return nil, resp.StatusCode, errors.New("research response exceeds the safe size limit")
	}

	if !utf8.Valid(body) {
		return nil, resp.StatusCode, errors.New("research response is not valid UTF-8")
	}

	return body, resp.StatusCode, nil
}

func validateResearchAPIURL(raw string) (*url.URL, error) {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return nil, errors.New("research API URL is malformed")
	}

	if !strings.EqualFold(u.Scheme, "https") {
		return nil, errors.New("research API requests must use HTTPS")
	}
	if u.Host == "" || u.Hostname() == "" {
		return nil, errors.New("research API URL must include a hostname")
	}
	if u.User != nil {
		return nil, errors.New("research API URL must not contain embedded credentials")
	}
	if u.Fragment != "" {
		return nil, errors.New("research API URL must not contain a fragment")
	}
	if u.Port() != "" {
		return nil, errors.New("research API URL must not specify a custom port")
	}

	host := strings.ToLower(strings.TrimSuffix(u.Hostname(), "."))
	if _, ok := allowedResearchAPIHosts[host]; !ok {
		return nil, fmt.Errorf("research API host %q is not allowed", host)
	}

	return u, nil
}

func (r *WebResearcher) researchHTTPClient() *http.Client {
	timeout := webResearchRequestTimeout

	var client http.Client
	if r != nil && r.Client != nil {
		client = *r.Client

		if client.Timeout > 0 && client.Timeout < timeout {
			timeout = client.Timeout
		}
	}

	client.Timeout = timeout
	client.CheckRedirect = func(
		_ *http.Request,
		_ []*http.Request,
	) error {
		return http.ErrUseLastResponse
	}

	return &client
}

func (r *WebResearcher) github(
	ctx context.Context,
	query string,
) []ResearchSource {
	rawURL := "https://api.github.com/search/repositories?q=" +
		url.QueryEscape(query) + "&per_page=5&sort=updated"

	body, status, err := r.get(ctx, rawURL)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{unavailableResearchSource(
			"GitHub repository search", rawURL, err, status,
		)}
	}

	var payload struct {
		Items []struct {
			Name        string `json:"full_name"`
			HTMLURL     string `json:"html_url"`
			Description string `json:"description"`
		} `json:"items"`
	}

	if err := jsonUnmarshal(body, &payload); err != nil {
		return []ResearchSource{parseErrorResearchSource(
			"GitHub repository search", rawURL, err,
		)}
	}

	out := []ResearchSource{{
		Name:      "GitHub repository search",
		URL:       rawURL,
		Status:    "retrieved",
		Title:     fmt.Sprintf("GitHub search returned %d repositories", len(payload.Items)),
		Retrieved: time.Now().UTC(),
	}}

	for _, item := range payload.Items {
		link := strings.TrimSpace(item.HTMLURL)
		if !validPublicResearchLink(link) {
			continue
		}

		out = append(out, ResearchSource{
			Name:      "GitHub repository",
			URL:       link,
			Status:    "retrieved",
			Title:     limitText(strings.TrimSpace(item.Name), 200),
			Snippet:   limitText(strings.TrimSpace(item.Description), 500),
			Retrieved: time.Now().UTC(),
		})
	}

	return out
}

func (r *WebResearcher) arxiv(
	ctx context.Context,
	query string,
) []ResearchSource {
	rawURL := "https://export.arxiv.org/api/query?search_query=all:" +
		url.QueryEscape(query) + "&start=0&max_results=5"

	body, status, err := r.get(ctx, rawURL)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{unavailableResearchSource(
			"arXiv research", rawURL, err, status,
		)}
	}

	var feed struct {
		Entries []struct {
			Title   string `xml:"title"`
			ID      string `xml:"id"`
			Summary string `xml:"summary"`
		} `xml:"entry"`
	}

	if err := xml.Unmarshal(body, &feed); err != nil {
		return []ResearchSource{parseErrorResearchSource(
			"arXiv research", rawURL, err,
		)}
	}

	out := []ResearchSource{{
		Name:      "arXiv research",
		URL:       rawURL,
		Status:    "retrieved",
		Title:     fmt.Sprintf("arXiv returned %d papers", len(feed.Entries)),
		Retrieved: time.Now().UTC(),
	}}

	for _, item := range feed.Entries {
		link := strings.TrimSpace(item.ID)
		if !validPublicResearchLink(link) {
			continue
		}

		out = append(out, ResearchSource{
			Name:      "arXiv paper",
			URL:       link,
			Status:    "retrieved",
			Title:     limitText(strings.Join(strings.Fields(item.Title), " "), webResearchMaxSourceTitle),
			Snippet:   limitText(strings.Join(strings.Fields(item.Summary), " "), webResearchMaxSourceSnippet),
			Retrieved: time.Now().UTC(),
		})
	}

	return out
}

func (r *WebResearcher) nvd(
	ctx context.Context,
	query string,
) []ResearchSource {
	rawURL := "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=" +
		url.QueryEscape(query) + "&resultsPerPage=5"

	body, status, err := r.get(ctx, rawURL)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{unavailableResearchSource(
			"NVD CVE lookup", rawURL, err, status,
		)}
	}

	var payload struct {
		Total           int `json:"totalResults"`
		Vulnerabilities []struct {
			CVE struct {
				ID           string `json:"id"`
				Descriptions []struct {
					Lang  string `json:"lang"`
					Value string `json:"value"`
				} `json:"descriptions"`
			} `json:"cve"`
		} `json:"vulnerabilities"`
	}

	if err := jsonUnmarshal(body, &payload); err != nil {
		return []ResearchSource{parseErrorResearchSource(
			"NVD CVE lookup", rawURL, err,
		)}
	}

	out := []ResearchSource{{
		Name:      "NVD CVE lookup",
		URL:       rawURL,
		Status:    "retrieved",
		Title:     fmt.Sprintf("NVD returned %d matching CVEs", payload.Total),
		Retrieved: time.Now().UTC(),
	}}

	for _, vulnerability := range payload.Vulnerabilities {
		id := strings.TrimSpace(vulnerability.CVE.ID)
		if id == "" || len(id) > 100 {
			continue
		}

		snippet := ""
		for _, description := range vulnerability.CVE.Descriptions {
			if strings.EqualFold(description.Lang, "en") {
				snippet = description.Value
				break
			}
		}

		out = append(out, ResearchSource{
			Name:      "NVD CVE record",
			URL:       "https://nvd.nist.gov/vuln/detail/" + url.PathEscape(id),
			Status:    "retrieved",
			Title:     id,
			Snippet:   limitText(strings.TrimSpace(snippet), webResearchMaxSourceSnippet),
			Retrieved: time.Now().UTC(),
		})
	}

	return out
}

func (r *WebResearcher) kenyaRSS(
	ctx context.Context,
	query string,
) []ResearchSource {
	rawURL := "https://news.google.com/rss/search?q=" +
		url.QueryEscape(query+" Kenya") +
		"&hl=en-KE&gl=KE&ceid=KE:en"

	body, status, err := r.get(ctx, rawURL)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{unavailableResearchSource(
			"Kenya technology-demand RSS", rawURL, err, status,
		)}
	}

	var feed struct {
		Items []struct {
			Title       string `xml:"title"`
			Link        string `xml:"link"`
			Description string `xml:"description"`
			PubDate     string `xml:"pubDate"`
		} `xml:"channel>item"`
	}

	if err := xml.Unmarshal(body, &feed); err != nil {
		return []ResearchSource{parseErrorResearchSource(
			"Kenya technology-demand RSS", rawURL, err,
		)}
	}

	out := []ResearchSource{{
		Name:      "Kenya technology-demand RSS",
		URL:       rawURL,
		Status:    "retrieved",
		Title:     fmt.Sprintf("RSS search returned %d news items", len(feed.Items)),
		Retrieved: time.Now().UTC(),
	}}

	for _, item := range feed.Items {
		link := strings.TrimSpace(item.Link)
		if !validPublicResearchLink(link) {
			continue
		}

		out = append(out, ResearchSource{
			Name:      "Kenya demand/news item",
			URL:       link,
			Status:    "retrieved",
			Title:     limitText(strings.Join(strings.Fields(item.Title), " "), webResearchMaxSourceTitle),
			Snippet:   limitText(strings.Join(strings.Fields(item.Description), " "), webResearchMaxSourceSnippet),
			Retrieved: time.Now().UTC(),
		})

		if len(out) >= 8 {
			break
		}
	}

	return out
}

func unavailableResearchSource(
	name string,
	rawURL string,
	err error,
	status int,
) ResearchSource {
	return ResearchSource{
		Name:      name,
		URL:       rawURL,
		Status:    "unavailable",
		Snippet:   errorText(err, status),
		Retrieved: time.Now().UTC(),
	}
}

func parseErrorResearchSource(
	name string,
	rawURL string,
	err error,
) ResearchSource {
	message := "response could not be parsed"
	if err != nil {
		message = limitText(err.Error(), 240)
	}

	return ResearchSource{
		Name:      name,
		URL:       rawURL,
		Status:    "parse_error",
		Snippet:   message,
		Retrieved: time.Now().UTC(),
	}
}

// validPublicResearchLink validates links displayed as research references.
// It does not fetch the destination.
func validPublicResearchLink(raw string) bool {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return false
	}

	if !strings.EqualFold(u.Scheme, "https") ||
		u.Host == "" ||
		u.Hostname() == "" ||
		u.User != nil ||
		u.Fragment != "" {
		return false
	}

	if u.Port() != "" {
		return false
	}

	host := strings.ToLower(strings.TrimSuffix(u.Hostname(), "."))
	if host == "" ||
		host == "localhost" ||
		strings.HasSuffix(host, ".localhost") ||
		strings.HasSuffix(host, ".local") ||
		strings.HasSuffix(host, ".internal") ||
		strings.HasSuffix(host, ".test") {
		return false
	}

	if ip := net.ParseIP(host); ip != nil {
		if ip.IsLoopback() ||
			ip.IsPrivate() ||
			ip.IsLinkLocalUnicast() ||
			ip.IsLinkLocalMulticast() ||
			ip.IsUnspecified() {
			return false
		}
	}

	return true
}

func deduplicateResearchSources(
	sources []ResearchSource,
	maxSources int,
) []ResearchSource {
	out := make([]ResearchSource, 0, minResearchInt(len(sources), maxSources))
	seen := make(map[string]struct{}, len(sources))

	for _, source := range sources {
		link := strings.TrimSpace(source.URL)
		if link != "" {
			if !validPublicResearchLink(link) {
				continue
			}

			key := strings.ToLower(link)
			if _, exists := seen[key]; exists {
				continue
			}
			seen[key] = struct{}{}
		}

		out = append(out, source)
		if maxSources > 0 && len(out) >= maxSources {
			break
		}
	}

	return out
}

func cleanResearchFindings(findings []string, maxItems int) []string {
	out := make([]string, 0, minResearchInt(len(findings), maxItems))
	seen := make(map[string]struct{})

	for _, finding := range findings {
		finding = strings.TrimSpace(finding)
		if finding == "" {
			continue
		}

		key := strings.ToLower(finding)
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}

		out = append(out, finding)
		if maxItems > 0 && len(out) >= maxItems {
			break
		}
	}

	return out
}

func minResearchInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func errorText(err error, status int) string {
	if err != nil {
		return limitText(err.Error(), 240)
	}
	return fmt.Sprintf("HTTP status %d", status)
}
