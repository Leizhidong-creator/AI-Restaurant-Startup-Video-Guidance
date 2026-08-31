# PocketMentor README Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a branded, research-grade README that explains PocketMentor's product value, technical method, author contribution, evidence model, social significance, reproducibility, and limitations.

**Architecture:** Keep `README.md` as the canonical narrative and Mermaid as the canonical format for relational diagrams. Store only two supplementary bitmap assets under `docs/assets/readme/`: an original brand hero and a real product screenshot. Derive every technical claim from the current code, knowledge manifest, verified release tests, or explicitly labeled portfolio observation.

**Tech Stack:** GitHub Markdown, Mermaid, shields.io static badges where truthful, HTML alignment supported by GitHub Markdown, Playwright/Chromium for local screenshots, AI raster image generation for the original hero.

## Global Constraints

- Product name is `口袋餐谋 / PocketMentor`.
- Hero headline is `把餐饮专家装进口袋`.
- `武汉大区前 10` must not appear.
- Competition recognition is limited to `2026 抖音 AI 创变者黑客松武汉大区赛优秀作品`.
- The README is Chinese-first and uses English only where it improves naming or technical precision.
- Existing watermarked character assets must not appear in README visuals.
- Metrics must be explained in context and must not imply diagnostic accuracy.
- Implemented behavior, development fallback, production recommendation, and known limitation must remain distinguishable.
- Mermaid is the source of truth for all structural diagrams.

---

### Task 1: Build The Verified Content Ledger

**Files:**
- Read: `4.产品-视频对照诊断MVP/engine/decision_core/knowledge/manifest.json`
- Read: `4.产品-视频对照诊断MVP/engine/decision_core/skill/restaurant-decision/SKILL.md`
- Read: `4.产品-视频对照诊断MVP/backend/src/yongge_online/videos/service.py`
- Read: `4.产品-视频对照诊断MVP/backend/src/yongge_online/knowledge/service.py`
- Read: `4.产品-视频对照诊断MVP/backend/src/yongge_online/knowledge/platform.py`
- Read: `4.产品-视频对照诊断MVP/backend/src/yongge_online/diagnosis/service.py`
- Read: `E:/A竞赛和项目/作品集文档.md`

**Interfaces:**
- Consumes: current repository implementation and user-authored portfolio evidence.
- Produces: a claim ledger used while drafting `README.md`.

- [ ] **Step 1: Verify current knowledge composition**

Run:

```powershell
Get-Content '4.产品-视频对照诊断MVP/engine/decision_core/knowledge/manifest.json'
```

Expected: 93 documents, 52 methods, 41 cases, with 52 reviewed, 25 golden, and 16 secondary records.

- [ ] **Step 2: Verify test totals from fresh runs**

Run:

```powershell
python -m pytest '4.产品-视频对照诊断MVP/engine/decision_core/tests' -q
python -m pytest '4.产品-视频对照诊断MVP/backend/tests' --ignore='4.产品-视频对照诊断MVP/backend/tests/live' -q
python -m pytest '4.产品-视频对照诊断MVP/integration/tests' -q
```

Expected: 51, 77, and 14 passing tests respectively.

- [ ] **Step 3: Record claim boundaries**

Use these exact labels while drafting:

```text
Implemented: code path exists and is covered by the sanitized snapshot.
Development path: temporary upload, lexical fallback, and local cache observation.
Production recommendation: vector retrieval, reranking, and durable object storage.
Known limitation: no guaranteed business outcome, POI is not traffic, browser camera support varies.
```

- [ ] **Step 4: Commit only if the ledger changes tracked files**

No commit is expected for this read-only task.

### Task 2: Create The Original Brand Hero

**Files:**
- Create: `docs/assets/readme/pocketmentor-hero.png`

**Interfaces:**
- Consumes: approved brand direction and hero copy from the design specification.
- Produces: a 1600x640 raster hero referenced by `README.md`.

- [ ] **Step 1: Generate the visual base**

Generate an original horizontal raster composition with an ink-black, jade-green, tomato-red, mustard-yellow, and paper-white palette. Show a friendly original pocket restaurant mentor holding a diagnostic clipboard and phone camera, with a restaurant storefront comparison path in the background. Keep the middle-left text-safe and avoid platform logos, third-party characters, watermarks, gradients, photorealistic faces, and embedded unreadable text.

- [ ] **Step 2: Apply the quality gate**

Reject and regenerate if the image contains a watermark, malformed hands, illegible pseudo-text, an existing brand logo, a generic stock-photo look, or a childish toy aesthetic that overwhelms the technical positioning.

- [ ] **Step 3: Verify dimensions and file size**

Run:

```powershell
magick identify docs/assets/readme/pocketmentor-hero.png
Get-Item docs/assets/readme/pocketmentor-hero.png | Select-Object Length
```

Expected: 1600x640 PNG or an aspect-equivalent crop, with a practical GitHub download size.

- [ ] **Step 4: Stage the asset**

```powershell
git add docs/assets/readme/pocketmentor-hero.png
```

### Task 3: Capture A Real Product Screenshot

**Files:**
- Create: `docs/assets/readme/product-overview.png`
- Read: `web/index.html`
- Read: `web/styles.css`
- Read: `web/app.js`

**Interfaces:**
- Consumes: the existing static H5 application.
- Produces: a representative 1440x900 or 1280x800 product screenshot referenced by `README.md`.

- [ ] **Step 1: Start the static frontend**

Run:

```powershell
python -m http.server 5173 --bind 127.0.0.1 --directory web
```

Expected: the frontend is available at `http://127.0.0.1:5173/`.

- [ ] **Step 2: Capture the real interface**

Use Chromium/Playwright at a desktop viewport. Wait for fonts and images, confirm the page is nonblank, then capture the first meaningful product state without browser chrome.

- [ ] **Step 3: Inspect the screenshot**

Check that no private data, broken image, missing video placeholder, overflow, overlap, or visible generation watermark appears. Crop only empty browser margins; do not fabricate product controls.

- [ ] **Step 4: Stage the screenshot**

```powershell
git add docs/assets/readme/product-overview.png
```

### Task 4: Write The Research-Grade README

**Files:**
- Modify: `README.md`
- Reference: `docs/superpowers/specs/2026-09-01-readme-redesign.md`
- Reference: `docs/assets/readme/pocketmentor-hero.png`
- Reference: `docs/assets/readme/product-overview.png`

**Interfaces:**
- Consumes: claim ledger, brand hero, product screenshot, and approved information architecture.
- Produces: the canonical public project narrative.

- [ ] **Step 1: Replace the hero and abstract**

Use the approved product name, headline, and supporting statement. Add only truthful navigation links and the competition recognition. Do not place unexplained numeric counters in the hero.

- [ ] **Step 2: Add the product value flow**

Create an accessible Mermaid flowchart from watched viral video through case deconstruction, user-store observation, aligned gap diagnosis, transformation action, and validation loop.

- [ ] **Step 3: Add the problem and method sections**

Explain why copying a viral store fails and how `Knowledge Base + Skill + Evidence Runtime` creates a mechanism-aligned comparison between the reference store and the user's store.

- [ ] **Step 4: Add the video and knowledge deep dives**

Document link/upload ingestion, validation, resolver fallback, content hashing, cache reuse, timestamped analysis, private knowledge ingestion, platform retrieval, evidence grades, and stable evidence IDs. Explicitly identify lexical retrieval as a safe public fallback and vector retrieval/reranking as a production recommendation.

- [ ] **Step 5: Add the real-time and Skill diagrams**

Use a Mermaid sequence diagram for H5/Realtime/backend/tools/report interaction and a flowchart for the Skill safety/action/evidence/judgment state machine.

- [ ] **Step 6: Add engineering contribution case studies**

Use a table with columns `具体问题`, `关键判断`, `实现`, `结果与边界`. Cover transferability, hallucinated evidence, missing现场 context, unstable tool calls, repeated analysis cost, large-video handling, and private retrieval.

- [ ] **Step 7: Add social value, evaluation, and limitations**

Define technology access as service accessibility, contextual observation, reusable knowledge, and verifiable decisions. Explain the 142 tests by layer. State limitations without minimizing them.

- [ ] **Step 8: Preserve accurate setup and security instructions**

Keep Windows and Unix environment setup clear, retain secret-management guidance, and link `SECURITY.md`.

- [ ] **Step 9: Stage the README**

```powershell
git add README.md
```

### Task 5: Verify Markdown, Mermaid, Links, Assets, And Security

**Files:**
- Test: `README.md`
- Test: `docs/assets/readme/pocketmentor-hero.png`
- Test: `docs/assets/readme/product-overview.png`

**Interfaces:**
- Consumes: completed README and assets.
- Produces: evidence that the public artifact is renderable and contains no known sensitive material.

- [ ] **Step 1: Scan forbidden and unsupported copy**

Run:

```powershell
rg -n '武汉大区前.?10|武汉大区前十|替代专家|保证成功|100%成功' README.md
```

Expected: no matches.

- [ ] **Step 2: Check local links and referenced assets**

Parse Markdown links and image paths, confirm every relative target exists, and verify there are no references to removed media such as `demo-case.mp4`.

- [ ] **Step 3: Validate Mermaid syntax**

Extract each Mermaid block and render it with Mermaid CLI or a compatible renderer. Expected: all diagrams parse without errors and remain readable at GitHub content width.

- [ ] **Step 4: Run content and secret scans**

```powershell
git diff --check
git grep -n -I -E '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]+PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{20,})' -- README.md docs/assets/readme
```

Expected: no whitespace errors and no credential-pattern matches.

- [ ] **Step 5: Review the rendered README**

Render locally or inspect on GitHub after push. Confirm the first viewport communicates brand, purpose, and product; diagrams do not overflow; tables remain readable; and no section looks like an unexplained metric wall.

### Task 6: Commit And Publish

**Files:**
- Commit: `README.md`
- Commit: `docs/assets/readme/pocketmentor-hero.png`
- Commit: `docs/assets/readme/product-overview.png`
- Commit: `docs/superpowers/plans/2026-09-01-readme-redesign.md`

**Interfaces:**
- Consumes: verified README deliverable.
- Produces: public GitHub README on `main`.

- [ ] **Step 1: Inspect the staged diff**

```powershell
git diff --cached --stat
git diff --cached -- README.md
```

Expected: only the planned README, assets, and design documentation are staged.

- [ ] **Step 2: Commit**

```powershell
git commit -m "docs: redesign project README"
```

- [ ] **Step 3: Push**

```powershell
git push origin main
```

- [ ] **Step 4: Verify remote state**

```powershell
git ls-remote origin refs/heads/main
git status --short --branch
```

Expected: remote `main` points to the new commit and the worktree is clean.
