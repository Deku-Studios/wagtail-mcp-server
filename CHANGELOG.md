# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial scaffold: Django app, settings resolver, auth backends, token models, CLI wrapper, OTel emitter, StreamField envelope contract, toolset shells for pages_query, pages_write, workflow, media, seo_query, seo_write.
- BSD-3-Clause LICENSE.
- GitHub Actions CI matrix across Python 3.11 / 3.12 and Wagtail 7.3.1 / main.
- pytest suite covering settings validation, envelope shape, and import invariants.
