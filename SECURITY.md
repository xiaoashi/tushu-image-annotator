# API and local data

Supply your own visual-model API key using `TUSHU_VISION_API_KEY`, or enter it in the local web settings dialog. The public repository contains no working credential. `.env.example` intentionally leaves the key blank; it is a reference and is not automatically loaded.

Keys entered in the page remain in the server process memory until it exits. Bootstrap and configuration responses return only configuration status, never the key. Images are sent only after the user selects them and confirms the displayed visual-service destination. Visual requests use HTTPS, do not follow redirects, and do not forward remote error bodies to the browser or logs.

A local developer may optionally maintain a private configuration outside the repository in their own Application Support directory. That file must not be copied into a delivery or Git commit. Application databases, working images, private reports and copyright registration details are excluded from public publication.

The web server binds to 127.0.0.1. Mutation requests require the local client token and same-origin checks. This is a single-user local application; do not expose its port to a public network.

Image contents and model responses are treated as data. Suggested categories and coordinates are validated, remain pending review, and never automatically certify negative samples or species identification.
