# RevelaAI Workspace Execution API

The unified workspace execution endpoints are:

    POST /api/workspace/execute
    POST /api/workspace/execute/multipart

Use the JSON endpoint for text and structured inputs. Use the multipart endpoint when a user selects an actual logo, photograph, scan, seal or other image file in RevelaCode; upload the file in the same request and it will be embedded in the exported document or deck.

Requests must carry a valid RevelaCode Bearer token. The route uses the existing
Smart AI entitlement, Productivity administrator controls, quota metering,
Meta Engineer/Sci Defender preflight, configured server-side model providers,
and the Productivity signed-file store.

## Request contract

| Field | Type | Purpose |
| --- | --- | --- |
| task | string | auto, document, code, ui_design, analytics, image, image_edit, or promotion |
| prompt | string | Required task instructions, up to 12,000 characters |
| title | string | Optional artifact title |
| format | string | word, pdf, powerpoint, spreadsheet, csv, or markdown |
| document_style | string | auto, official, or standard; auto detects formal letters, memos and submissions |
| official_metadata | object | Optional exact particulars: organization, recipient, address, date, reference, subject, salutation, signatory, cc and enclosures |
| embedded_images | array | Optional image objects with image_base64, mime_type, alt_text, placement and width_inches |
| language | string | Optional source-code language hint |
| dataset | string/object/array | CSV text, a headers/rows object, or an array of row objects |
| image_base64 | string | Optional JPEG, PNG, or WEBP base64/data URL for editing |
| mime_type | string | MIME type for the uploaded image |
| operations | array | Up to 12 bounded image-edit operations |
| image_options | object | Existing image/design studio options |
| sections | array | Optional structured DOCX sections |
| slides | array | Optional structured PowerPoint slides |

When task is auto, the router uses the supplied dataset and prompt intent to select a
processor. For stable integrations, clients should send task explicitly.

## Examples

Create a professional document:

~~~json
{
  "task": "document",
  "format": "word",
  "title": "School Technology Proposal",
  "prompt": "Prepare a professional proposal using the facts and scope supplied in this request."
}
~~~

Generate a responsive UI prototype:

~~~json
{
  "task": "ui_design",
  "title": "RevelaCode Admin Dashboard",
  "prompt": "Design a responsive admin dashboard with a collapsible navigation, KPI cards, a recent activity table, empty/loading/error states, and mobile navigation."
}
~~~

Analyze a dataset:

~~~json
{
  "task": "analytics",
  "prompt": "Profile fees by class, check missing values and duplicates, and summarize fee amounts.",
  "dataset": {
    "headers": ["class", "fees"],
    "rows": [["Grade 1", 12000], ["Grade 2", 15000], ["Grade 1", 12000]]
  }
}
~~~

Edit a supplied image:

~~~json
{
  "task": "image_edit",
  "prompt": "Crop and improve the supplied image.",
  "mime_type": "image/png",
  "image_base64": "BASE64_IMAGE_DATA",
  "operations": [
    {"type": "crop", "left": 0, "top": 0, "right": 0.9, "bottom": 1},
    {"type": "contrast", "factor": 1.15},
    {"type": "sharpness", "factor": 1.2}
  ]
}
~~~

Create a RevelaCode campaign:

~~~json
{
  "task": "promotion",
  "title": "RevelaCode Product Campaign",
  "prompt": "Promote the supplied RevelaCode product and audience. Use only facts in the brief; prepare a social caption, WhatsApp message, call to action, campaign document, and poster."
}
~~~

## Execution and verification boundaries

- DOCX, PDF, PPTX, XLSX, CSV, Markdown, HTML UI prototypes, code files, and edited PNG assets are delivered using private signed artifact links.
- Signed artifact downloads expire after the configured retention period (24 hours by default for this route).
- Dataset statistics are computed deterministically from the supplied rows. The analysis workbook includes quality, profile, statistics, category, and preview sheets.
- Image edits accept JPEG, PNG and WEBP input, up to 4 MB and 20 megapixels. Supported operations are brightness, contrast, saturation, sharpness, grayscale, invert, blur, rotate, flip, crop, resize, and text overlay.
- Image/logo/graphic generation is delegated to the existing RevelaAI design and image pipeline. It requires the account's image-generation entitlement.
- Generated source code is saved as a file. Python and JSON receive parser validation; other listed languages are packaged without a runtime claim. This route never executes generated code. Use the separately provisioned isolated sandbox for approved execution.
- HTML UI prototypes are standalone files. The route does not deploy them, create a Figma project, or connect them to live APIs.
- Pixel operations do not provide semantic object removal, generative inpainting, or guaranteed preservation of every detail. Such capabilities require an image-editing model/provider configured for image-to-image edits.
- The route uses the server's already configured model providers. It does not bundle a foundation model or guarantee equivalence to a commercial frontier assistant.

## Default daily allowance

The workspace execution tool is registered in the Productivity catalog and can be disabled by a platform administrator. Current default daily limits are 2 executions for Free, 30 for Plus, and 100 for Pro. The existing image-generation entitlement is checked separately for image generation, image editing, and campaign posters.


## Official correspondence and image/logo embedding

For official letters, institutional submissions, formal requests, memoranda, proposals and reports, use the official document style. The engine asks the configured text model for a structured document layout and keeps formal particulars separate from body sections. Supply any details that must be exact in official_metadata; explicit values override model-extracted values. Missing recipients, reference numbers, addresses, dates and signatories are left blank rather than invented.

Supported official metadata keys include:

- document_type: letter, memo, submission, proposal or report
- organization, organization_address
- date, reference
- recipient, recipient_organization, recipient_address
- sender, subject, salutation
- closing, signatory, signatory_title
- cc, enclosures

### Upload an existing logo from RevelaCode

Use multipart form-data so the frontend can send the user's selected file directly. The image is validated, converted to a document-safe PNG representation in memory, and placed in the actual DOCX/PDF/PPTX output. Source upload bytes are not retained as a separate permanent image.

Example form fields:

| Field | Value |
| --- | --- |
| task | document |
| format | word or pdf |
| document_style | official |
| prompt | Write a formal institutional partnership request using the supplied details. Do not invent missing particulars. |
| official_metadata | JSON object containing exact recipient, date, reference, organization and signatory details |
| image_placement | header, cover or inline |
| logo | The actual PNG/JPEG/WEBP file selected by the user |

The file field can be named logo, image, images (repeatable), or attachment. For PowerPoint use format=powerpoint; the default multipart image placement becomes title_slide. Use image_placement=all_slides to place a logo on every slide.

For JSON clients, pass the image bytes as a base64 data URL or base64 string inside embedded_images:

~~~json
{
  "task": "document",
  "format": "word",
  "document_style": "official",
  "title": "Institutional Partnership Request",
  "prompt": "Prepare an official letter requesting a meeting. Use only the particulars supplied.",
  "official_metadata": {
    "document_type": "letter",
    "organization": "RevelaCode Software Solutions",
    "date": "11 November 2026",
    "recipient": "The Conference Secretary",
    "recipient_organization": "West Kenya Conference",
    "subject": "Request for an institutional demonstration",
    "salutation": "Dear Conference Secretary,",
    "closing": "Yours faithfully,",
    "signatory": "Musombi William",
    "signatory_title": "Founder and Full-Stack Developer"
  },
  "embedded_images": [
    {
      "image_base64": "BASE64_OR_DATA_URL",
      "mime_type": "image/png",
      "alt_text": "RevelaCode logo",
      "placement": "header",
      "width_inches": 1.4
    }
  ]
}
~~~

Image rules: PNG, JPEG and WEBP inputs; up to 4 MB per image, 8 MB combined and 20 megapixels per image. DOCX supports header, cover and inline placement. PPTX supports title_slide, slide with slide_index, and all_slides. Images are validated before embedding. DOCX, PDF preview and PPTX output all contain the selected image; the API returns an images_embedded count.

The frontend must forward the image bytes selected or uploaded by the user to this endpoint. The backend cannot silently access an unrelated file elsewhere in the user's account or browser.
