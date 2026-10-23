# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-23

### Added

- Split images and PDF pages with several items (receipts, photos, cards) into one image per item
- Classic detection with OpenCV, no model needed
- Straightening and perspective correction, with edges measured at full resolution
- Thin background slivers along the edges are cut off
- Shadows next to items are not cut out with them
- Whole page is kept if nothing is found
- Optional vision model on any OpenAI-compatible server: finds touching items and items on similar backgrounds, turns items upright
- Debug output with all found items outlined
- Web page (`image-splitter serve`) to check and correct frames by hand: move corners, move, draw, delete and rotate frames, download all parts as ZIP
- Sample images for typical cases, with the script that generates them; "Try samples" on the web page loads them
- Docker image and `compose.yaml`: the web page with one command, answering only requests for localhost
- `--allowed-hosts` / `IMAGE_SPLITTER_ALLOWED_HOSTS` to name the host names the web page answers to
- Command-line tool and Python API (`split`, `split_image`, `split_many`, `draw_parts`, `cut`)

[Unreleased]: https://github.com/hamidmergan/image-splitter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hamidmergan/image-splitter/releases/tag/v0.1.0
