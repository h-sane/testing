# SARA Modern Assistant UI Plan (UI Expert Reviewed)

Date: 2026-04-20
Owner: Hussain + Copilot
Target stack: PyQt5
Scope: Unified dashboard and widget modernization with a strict implementation order.

## 1) Objective

Build a production-quality SARA assistant interface that feels modern, readable, alive, and reliable on low-resource hardware.

Mandatory outcomes:

- Strong visual hierarchy and spacing
- Clear shell layout and navigation
- High-quality chat UX
- Living voice presence through animated bubble states
- Reusable context/status cards
- Accessible keyboard-first interaction
- Fast rendering with no heavy visual effects

## 2) Non-Negotiable Build Order (Strict)

This order is locked. Do not start a later stage before the previous stage passes acceptance.

1. Tokens + theme
2. Layout shell
3. Chat system
4. Voice bubble
5. Context panel
6. Motion
7. Polish

## 3) Task Breakdown From UI Expert Review

## Task 1: Design System (Mandatory First)

Create:

- sara/ui/theme/tokens.py

Define in tokens.py:

- Colors: use the exact UI expert hex palette with no substitutions
- Spacing scale: 4, 8, 12, 16, 24
- Radius scale: 8, 12, 16
- Typography sizes: define clear title, section, body, caption scales

Rules:

- All component styling must read from tokens
- No hardcoded colors, spacing, or radius values in components

Acceptance gate:

- tokens.py exists and contains all required token groups
- New UI components compile with token-driven values only

## Task 2: Core Layout Shell

Implement application shell as:

QMainWindow

- Left Nav (fixed width: 72 collapsed / 200 expanded)
- Center Panel (chat + composer)
- Right Context Panel (collapsible)

Required Qt structure:

- QSplitter for center + right panel behavior
- QStackedWidget for top-level modes

Modes:

- Assistant
- Tasks and Runs
- Apps and Discovery
- Memory
- Settings

Acceptance gate:

- Left nav supports collapsed and expanded widths
- Right context panel can collapse/expand without layout break
- Resize behavior remains stable across small and large windows

## Task 3: Chat System (High Priority)

Create:

- sara/ui/components/message_card.py
- sara/ui/components/chat_container.py

Chat rules:

- Max message width: 720px
- Vertical message spacing: 16px
- Smooth scroll to latest message

Must support:

- user_message()
- assistant_message()
- code_block()

Acceptance gate:

- Message cards render consistently with token spacing/typography
- Code block rendering is visually distinct and readable
- Scroll behavior remains smooth under long conversations

## Task 4: Voice Bubble Component

Create:

- sara/ui/components/voice_bubble.py

Required states:

- idle
- listening
- processing
- speaking
- error

Animation requirements:

- Use QPropertyAnimation
- Animate opacity + scale
- Keep transitions responsive and clear

Acceptance gate:

- State machine can switch all 5 states reliably
- Visual state change is understandable without reading text logs

## Task 5: Context Panel Cards

Create reusable primitives:

- sara/ui/components/info_card.py
- sara/ui/components/status_chip.py

Implement cards:

- ActiveTaskCard
- PlanCard
- HealthCard

Acceptance gate:

- Cards share one consistent base style
- Status chips correctly render Idle, Running, Error states

## Task 6: Top Bar

Build minimal top bar with:

- App name
- Status chip (Idle / Running / Error)
- Quick toggle buttons

Acceptance gate:

- Top bar remains uncluttered and stable across window sizes
- Runtime status is always visible at a glance

## Task 7: Styling System Migration

Replace global hardcoded QSS with generated stylesheet system:

- sara/ui/theme/stylesheets.py

Rules:

- No hardcoded color values in components
- All styles derive from tokens
- Component selectors remain organized and maintainable

Acceptance gate:

- Existing global style usage is removed from new shell/components
- Theme changes can be made by editing tokens only

## Task 8: Motion Implementation

Implement:

- Fade-in for new chat messages
- Step reveal animation for task/progress stream
- Voice bubble animations for state transitions

Timing constraint:

- All transitions under 300ms

Acceptance gate:

- Motion enhances clarity and does not slow interaction
- No stutter during rapid status updates

## Task 9: Accessibility Requirements

Must include:

- Focus ring for all interactive controls
- Full keyboard navigation path
- High-contrast text and status readability

Acceptance gate:

- Keyboard-only use is possible for critical flows
- Focus visibility is consistent in every panel

## Task 10: Performance Rules

Hard constraints:

- No blur effects
- Avoid repaint loops
- Reuse widgets instead of frequent rebuilds

Acceptance gate:

- UI remains responsive on 8GB RAM, no-GPU machine
- No excessive CPU spikes from animation or rendering

## 4) Implementation File Plan

Core theme:

- sara/ui/theme/tokens.py
- sara/ui/theme/stylesheets.py

Core components:

- sara/ui/components/message_card.py
- sara/ui/components/chat_container.py
- sara/ui/components/voice_bubble.py
- sara/ui/components/info_card.py
- sara/ui/components/status_chip.py

Shell integration targets:

- sara/ui/chat_widget.py
- sara/ui/widget.py

Migration policy:

- Introduce new shell/components first
- Incrementally migrate old views
- Keep existing execution and backend orchestration untouched

## 5) Phase Plan (Mapped To Strict Priority)

Phase A: Tokens + Theme

- Build tokens.py and stylesheets.py
- Refactor baseline component styling to token usage

Phase B: Layout Shell

- Implement QMainWindow shell with nav, center, right context
- Add QSplitter and QStackedWidget mode framework

Phase C: Chat System

- Add message_card and chat_container
- Enforce 720px max width and 16px spacing

Phase D: Voice Bubble

- Implement voice_bubble component and state transitions
- Wire to runtime state changes

Phase E: Context Panel

- Implement info_card, status_chip, and required cards
- Bind card content to live state and plan summaries

Phase F: Motion

- Add fade/reveal/voice animations under 300ms
- Verify smoothness under continuous updates

Phase G: Polish

- Accessibility hardening
- Keyboard path validation
- Final visual consistency pass

## 6) Definition of Done

The rewrite is complete only when all items below are true:

1. tokens.py is the single source of styling values.
2. Shell layout matches the required 3-region architecture.
3. Chat UI uses message cards and supports code blocks.
4. Voice bubble supports all five states with animation.
5. Context panel uses reusable card and chip primitives.
6. Top bar always shows app identity and runtime state.
7. Motion stays under 300ms and feels intentional.
8. Keyboard navigation and focus ring are consistently implemented.
9. Performance constraints are respected (no blur, no repaint loops, widget reuse).

## 7) Execution Notes

- Keep this as an implementation contract, not a concept document.
- If any requested item conflicts with performance constraints, choose performance-safe behavior first.
- Do not add decorative effects that do not improve status clarity, interaction feedback, or orientation.
