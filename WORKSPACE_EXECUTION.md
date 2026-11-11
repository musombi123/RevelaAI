# RevelaAI Workspace Execution API

The unified workspace execution endpoint is:

    POST /api/workspace/execute

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
