package genesis

import (
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

// WebResearcher uses only Go's standard library. It never executes downloaded content.
// Vendor/paywalled and local-demand sources are represented as research links, not fabricated results.
type WebResearcher struct {
	Client  *http.Client
	Offline bool
}

func NewWebResearcher() *WebResearcher {
	offline := strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "1") || strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "true")
	return &WebResearcher{Client: &http.Client{Timeout: 5 * time.Second}, Offline: offline}
}

func (r *WebResearcher) Research(ctx context.Context, demand string) (ResearchEvidence, error) {
	if ctx == nil { ctx = context.Background() }
	select { case <-ctx.Done(): return ResearchEvidence{}, ctx.Err(); default: }
	now := time.Now().UTC()
	q := strings.TrimSpace(demand)
	e := ResearchEvidence{ID: newID("research"), Query: q, CollectedAt: now, Mode: "online-with-offline-fallback", Sources: []ResearchSource{}, Findings: []string{}}
	if r.Offline {
		e.Mode = "offline"
	}
	enc := url.QueryEscape(q)
	links := []ResearchSource{
		{Name: "WIPO Patentscope search", URL: "https://patentscope.wipo.int/search/en/search.jsf?query=" + enc, Status: "reference_link"},
		{Name: "ISO standards search", URL: "https://www.iso.org/search.html?q=" + enc, Status: "reference_link"},
		{Name: "KEBS standards catalogue", URL: "https://www.kebs.org/", Status: "reference_link"},
		{Name: "Jumia Kenya product research", URL: "https://www.jumia.co.ke/catalog/?q=" + enc, Status: "reference_link"},
		{Name: "Mouser component research", URL: "https://www.mouser.com/c/?q=" + enc, Status: "reference_link"},
		{Name: "New semiconductor/chip catalogue research", URL: "https://www.digikey.com/en/products", Status: "reference_link"},
		{Name: "Kenya demand/news search", URL: "https://news.google.com/rss/search?q=" + url.QueryEscape(q+" Kenya demand") + "&hl=en-KE&gl=KE&ceid=KE:en", Status: "reference_link"},
	}
	e.Sources = append(e.Sources, links...)
	if !r.Offline {
		// Independent public sources run in parallel under one bounded deadline. Results are
		// joined in a stable order so evidence bundles remain reproducible.
		researchCtx, cancel := context.WithTimeout(ctx, 13*time.Second)
		defer cancel()
		collectors := []func(context.Context, string) []ResearchSource{r.github, r.arxiv, r.nvd, r.kenyaRSS}
		results := make([][]ResearchSource, len(collectors))
		var wg sync.WaitGroup
		for i, collect := range collectors {
			wg.Add(1)
			go func(index int, fn func(context.Context, string) []ResearchSource) {
				defer wg.Done()
				results[index] = fn(researchCtx, q)
			}(i, collect)
		}
		wg.Wait()
		for _, records := range results {
			e.Sources = append(e.Sources, records...)
		}
	}
	if err := ctx.Err(); err != nil { return ResearchEvidence{}, err }
	usable := 0
	for _, s := range e.Sources {
		if s.Status == "retrieved" || s.Status == "reference_link" {
			usable++
		}
	}
	e.Findings = append(e.Findings, fmt.Sprintf("Collected %d source records; %d are direct research links or retrieved results.", len(e.Sources), usable))
	e.Findings = append(e.Findings, "Search-link records are leads only; they are not represented as verified prices, standards compliance, patent clearance, or market demand.")
	return e, nil
}

func (r *WebResearcher) get(ctx context.Context, rawURL string) ([]byte, int, error) {
	client := r.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("User-Agent", "RevelaGenesis/"+Version+" (+https://github.com/musombi123/RevelaAI)")
	req.Header.Set("Accept", "application/json, application/atom+xml, application/xml, text/xml")
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return body, resp.StatusCode, err
}

func (r *WebResearcher) github(ctx context.Context, q string) []ResearchSource {
	u := "https://api.github.com/search/repositories?q=" + url.QueryEscape(q) + "&per_page=5&sort=updated"
	body, status, err := r.get(ctx, u)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{{Name: "GitHub repository search", URL: u, Status: "unavailable", Snippet: errorText(err, status), Retrieved: time.Now().UTC()}}
	}
	var payload struct {
		Items []struct {
			Name        string `json:"full_name"`
			HTMLURL     string `json:"html_url"`
			Description string `json:"description"`
		} `json:"items"`
	}
	if jsonErr := jsonUnmarshal(body, &payload); jsonErr != nil {
		return []ResearchSource{{Name: "GitHub repository search", URL: u, Status: "parse_error", Snippet: jsonErr.Error(), Retrieved: time.Now().UTC()}}
	}
	out := []ResearchSource{{Name: "GitHub repository search", URL: u, Status: "retrieved", Title: fmt.Sprintf("GitHub search returned %d repositories", len(payload.Items)), Retrieved: time.Now().UTC()}}
	for _, it := range payload.Items {
		if it.HTMLURL != "" {
			out = append(out, ResearchSource{Name: "GitHub repository", URL: it.HTMLURL, Status: "retrieved", Title: limitText(it.Name, 200), Snippet: limitText(it.Description, 500), Retrieved: time.Now().UTC()})
		}
	}
	return out
}

func (r *WebResearcher) arxiv(ctx context.Context, q string) []ResearchSource {
	u := "https://export.arxiv.org/api/query?search_query=all:" + url.QueryEscape(q) + "&start=0&max_results=5"
	body, status, err := r.get(ctx, u)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{{Name: "arXiv research", URL: u, Status: "unavailable", Snippet: errorText(err, status), Retrieved: time.Now().UTC()}}
	}
	var feed struct {
		Entries []struct {
			Title   string `xml:"title"`
			ID      string `xml:"id"`
			Summary string `xml:"summary"`
		} `xml:"entry"`
	}
	if xmlErr := xml.Unmarshal(body, &feed); xmlErr != nil {
		return []ResearchSource{{Name: "arXiv research", URL: u, Status: "parse_error", Snippet: xmlErr.Error(), Retrieved: time.Now().UTC()}}
	}
	out := []ResearchSource{{Name: "arXiv research", URL: u, Status: "retrieved", Title: fmt.Sprintf("arXiv returned %d papers", len(feed.Entries)), Retrieved: time.Now().UTC()}}
	for _, it := range feed.Entries {
		if it.ID != "" {
			out = append(out, ResearchSource{Name: "arXiv paper", URL: strings.TrimSpace(it.ID), Status: "retrieved", Title: limitText(strings.Join(strings.Fields(it.Title), " "), 300), Snippet: limitText(strings.Join(strings.Fields(it.Summary), " "), 700), Retrieved: time.Now().UTC()})
		}
	}
	return out
}

func (r *WebResearcher) nvd(ctx context.Context, q string) []ResearchSource {
	u := "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=" + url.QueryEscape(q) + "&resultsPerPage=5"
	body, status, err := r.get(ctx, u)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{{Name: "NVD CVE lookup", URL: u, Status: "unavailable", Snippet: errorText(err, status), Retrieved: time.Now().UTC()}}
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
	if jsonErr := jsonUnmarshal(body, &payload); jsonErr != nil {
		return []ResearchSource{{Name: "NVD CVE lookup", URL: u, Status: "parse_error", Snippet: jsonErr.Error(), Retrieved: time.Now().UTC()}}
	}
	out := []ResearchSource{{Name: "NVD CVE lookup", URL: u, Status: "retrieved", Title: fmt.Sprintf("NVD returned %d matching CVEs", payload.Total), Retrieved: time.Now().UTC()}}
	for _, v := range payload.Vulnerabilities {
		title := v.CVE.ID
		snippet := ""
		for _, d := range v.CVE.Descriptions {
			if d.Lang == "en" {
				snippet = d.Value
				break
			}
		}
		out = append(out, ResearchSource{Name: "NVD CVE record", URL: "https://nvd.nist.gov/vuln/detail/" + url.PathEscape(title), Status: "retrieved", Title: title, Snippet: limitText(snippet, 700), Retrieved: time.Now().UTC()})
	}
	return out
}

func errorText(err error, status int) string {
	if err != nil {
		return limitText(err.Error(), 240)
	}
	return fmt.Sprintf("HTTP status %d", status)
}

func (r *WebResearcher) kenyaRSS(ctx context.Context, q string) []ResearchSource {
	u := "https://news.google.com/rss/search?q=" + url.QueryEscape(q+" Kenya") + "&hl=en-KE&gl=KE&ceid=KE:en"
	body, status, err := r.get(ctx, u)
	if err != nil || status < 200 || status >= 300 {
		return []ResearchSource{{Name: "Kenya technology-demand RSS", URL: u, Status: "unavailable", Snippet: errorText(err, status), Retrieved: time.Now().UTC()}}
	}
	var feed struct {
		Items []struct {
			Title       string `xml:"title"`
			Link        string `xml:"link"`
			Description string `xml:"description"`
			PubDate     string `xml:"pubDate"`
		} `xml:"channel>item"`
	}
	if xmlErr := xml.Unmarshal(body, &feed); xmlErr != nil {
		return []ResearchSource{{Name: "Kenya technology-demand RSS", URL: u, Status: "parse_error", Snippet: xmlErr.Error(), Retrieved: time.Now().UTC()}}
	}
	out := []ResearchSource{{Name: "Kenya technology-demand RSS", URL: u, Status: "retrieved", Title: fmt.Sprintf("RSS search returned %d news items", len(feed.Items)), Retrieved: time.Now().UTC()}}
	for _, item := range feed.Items {
		link := strings.TrimSpace(item.Link)
		if link == "" {
			continue
		}
		out = append(out, ResearchSource{Name: "Kenya demand/news item", URL: link, Status: "retrieved", Title: limitText(strings.Join(strings.Fields(item.Title), " "), 300), Snippet: limitText(strings.Join(strings.Fields(item.Description), " "), 700), Retrieved: time.Now().UTC()})
		if len(out) >= 8 {
			break
		}
	}
	return out
}
