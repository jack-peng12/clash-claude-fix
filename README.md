# clash-claude-fix

A proxy compatibility toolkit that helps developers in proxy-dependent regions reliably access AI APIs (OpenAI, Claude) through Clash Verge and FLClash. Fixes login issues, DNS leaks, and WebRTC leakage using automatic override scripts.

## Features

- Automatic override scripts for Clash Verge and FLClash
- Fixes DNS leaks and WebRTC leakage affecting API connectivity
- Stable proxy rule configs for OpenAI and Claude API endpoints
- Works in restricted network environments across Asia and other regions

## Usage

1. Download `clash-verge-override.js` or `flclash-override.js`
2. Load it as an override script in your Clash client
3. Restart the client — connectivity issues should be resolved

## Roadmap

- [ ] Codex-powered auto-generation of proxy rule configs for OpenAI API endpoints
- [ ] CI pipeline: Codex detects OpenAI API changes → opens PR with updated configs automatically
- [ ] Compatibility test suite driven by Codex for every major API update
- [ ] Extend proxy support to additional OpenAI services (Assistants API, Realtime API)

## License

MIT
