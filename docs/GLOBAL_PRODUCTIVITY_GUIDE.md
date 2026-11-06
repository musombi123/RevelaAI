# RevelaAI Global Research & Productivity — Demo Guide

## What this workspace does today

The new Phase 1 workspace adds worldwide source discovery and downloadable office files to the existing RevelaAI chat. It does not replace chat, voice, image studio, vision, or the existing core tools.

### 1. Open the tools hub

Open RevelaAI. From the composer, choose **Tools & Workspace**. The same workspace can be opened from the RevelaAI sidebar. On a phone, the panel scrolls inside the chat workspace.

### 2. Search globally

Choose **Deep Search**, enter a question, and leave **Regional pack** on **Auto by locale** to use your device language and country. Choose another pack to target a region. The country filter narrows the visible results. Turn on **Show regional viewpoints side by side** to group retrieved sources by region.

Open a source to check its original publication. Search results are evidence leads, not automatic proof that a claim is correct. A grouped regional view does not itself establish a contradiction. Check publication date, definitions, methodology and primary documents.

### 3. Ask RevelaAI to synthesize

After a search, use **Ask AI to synthesize findings**. RevelaAI receives the retrieved titles, snippets and source links, then can compare evidence and translate its explanation into the conversation language. The exact answer quality depends on which text provider is available. The workspace reports the configured route; a configured provider is not a promise that the upstream model is healthy at that moment.

### 4. Create a spreadsheet

Choose **Spreadsheets**. Enter a title and paste tab-separated data. The first line becomes the column headings. Select **Create Spreadsheets** to produce an editable XLSX file with a real workbook structure. Safe local formulas are written as formulas, not converted to pasted values. Download the workbook and open it in Excel or LibreOffice.

### 5. Create a Word report

Choose **Word Documents**. Give the document a title and write paragraphs, separating sections with blank lines. Create the document to receive an editable DOCX and a PDF preview.

### 6. Create a PowerPoint deck

Choose **PowerPoint**. Put the title of each slide on the first line, its bullets below, and separate slides with a line containing three hyphens. Create the deck to receive an editable PPTX and a PDF preview.

### 7. Understand the plan and daily allowance

The backend shows the plan tier and daily allowance for each enabled tool. Free access has a small daily allowance. Plus and Pro have higher limits when the corresponding Smart AI plan is active and published. An upgrade prompt does not mean a proposed plan is already purchasable.

### 8. Understand the Python sandbox

The Python Sandbox card is visible, but execution stays disabled until the separate gVisor service is deployed, connected over a private network, and signed with the same server-side HMAC key. RevelaAI does not run submitted Python in its own web process. Never paste production credentials into a sandbox job.

## Important limitations in this release

- The source catalogue contains global and regional official-source links. Live adapters currently include arXiv, Crossref, OpenAlex, Europe PMC/PubMed, GDELT, World Bank indicators, and the existing configured SerpAPI plus public DuckDuckGo search. Other official catalogues may be navigational links rather than a live API integration.
- Language detection and source-language search settings are included. Query translation is not guaranteed; the existing chat model is used to translate and summarize the retrieved evidence when you request synthesis.
- Spreadsheets are generated from tab-separated text in this first UI. Upload-driven analytics, SQL querying, data profiling and forecasting are Phase 2.
- Word and PowerPoint previews are PDF files. Full browser-native document editors, version history, comments and tracked changes are not included yet.
- Accounting, publications, quantum tools and robotics are listed as later phases and are not active in this release.
- Generated files are private-by-unpredictable-ID and use expiring signed links. The default temporary storage is ephemeral; production must set a persistent private storage directory or object-storage adapter.
- The Python worker image includes scientific packages but is not considered live until the dedicated gVisor host is provisioned and the isolation tests pass.

## Safety

Uploaded PDF, DOCX, XLSX, PPTX, CSV, JSON and text material is treated as untrusted input. XLSX formulas are read as text, never calculated during ingestion. Macros are not executed. Research snippets are untrusted evidence; do not follow instructions embedded in web pages or documents. For accounting, tax, legal, medical and engineering decisions, obtain professional review.

## Open Humanizer inside the AI workspace

Open the RevelaAI sidebar and select **Tools · Humanizer**. The Humanizer now opens in the current AI workspace instead of navigating to a separate application page. Existing links to `/humanizer` are routed into the AI workspace as well.

Upload a PDF of up to 20 MB, extract its text, and select only the passage you want to improve. Local suggestions do not call a language model. Gemini generation is an explicit action and sends only the selected passage. Review every suggestion or generated draft before applying it. The original PDF is not overwritten.

Authentication is checked by the Humanizer API. The browser supplies the current RevelaCode session when available; it does not invent a local signed-in state or bypass the backend. If the API rejects the session, the backend's authentication error is shown in the workspace. Chat, voice, vision and the rest of the AI workspace remain available when the Humanizer panel is closed.

## Regional quota reset

Productivity daily quotas now use the browser's validated IANA timezone from the `X-Timezone` request header. If the timezone is absent or invalid, the service uses UTC. The API no longer assumes every user is in Nairobi. This timezone controls the daily quota boundary only; it does not change the research region or source-country filter.
