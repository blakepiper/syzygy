# TUI Animation Design Specification

## Purpose

Add a coherent animation system to an existing terminal user interface that is already functional but visually static or minimally animated.

The goal is not to imitate graphical desktop software. The goal is to make the interface feel responsive, deliberate, and alive while remaining recognizably terminal-native.

Animations should emphasize:

- state changes
- hierarchy
- causality
- focus
- completion
- errors and warnings
- objects entering or leaving the interface
- relationships between actions and their results

The overall design philosophy is expressive but restrained. Important actions should have visible choreography rather than appearing instantaneously, but animation must never make routine interaction feel slow.

---

# 1. Core Principles

## 1.1 Animate Meaning, Not Decoration

Every animation should communicate something.

Good uses:

- a panel appearing because the user opened it
- an item moving because its position changed
- a result emerging after processing
- a selected object reacting to an action
- a section collapsing into its new location
- an error briefly shaking or flashing
- a completed operation settling into its final state

Avoid continuous decorative motion with no informational purpose.

The user should be able to infer what changed by watching the animation.

---

## 1.2 Actions Should Have Choreography

Avoid instantaneous transitions when an important state change occurs.

Prefer:

```text
anticipation
→ transition
→ emphasis
→ settle
```

For example:

```text
user activates control
→ control depresses or flashes
→ destination content appears
→ destination briefly receives emphasis
→ interface settles
```

The entire sequence may last only 150–400 ms.

The important quality is that the action feels caused by the user's input.

---

## 1.3 Preserve Responsiveness

Animation must never delay input processing.

Input handling and animation rendering must be independent.

The application should accept input immediately even while visual transitions are still completing, unless interaction during the transition would produce an invalid state.

Prefer canceling, merging, or accelerating animations rather than blocking interaction.

---

# 2. Animation System Architecture

Introduce a small animation layer between application state and rendering.

Recommended conceptual architecture:

```text
Application State
      ↓
UI State
      ↓
Animation Manager
      ↓
Animated Scene
      ↓
Terminal Renderer
```

The application owns logical state.

The animation system owns temporary visual state.

Do not encode animation timing inside business logic.

Avoid constructs such as:

```text
performAction()
sleep(100)
renderSomething()
sleep(100)
renderSomethingElse()
```

Instead:

```text
performAction()
animations.trigger("result-reveal", target)
```

The application should remain correct if animations are disabled entirely.

---

# 3. Animated Properties

Where practical, UI elements should expose some subset of the following animated properties:

```text
x
y

width
height

visibleWidth
visibleHeight

brightness
foregroundColor
backgroundColor

emphasis
shakeX
shakeY

representation
zIndex

clipRect

age
progress
```

Positions and dimensions should be stored internally as floating-point values even though terminal cells are discrete.

Example:

```text
x = 18.0
x = 18.4
x = 18.9
x = 19.5
x = 20.0
```

Rendering may round these values to terminal coordinates.

This still produces better timing and motion than updating integer positions directly.

---

# 4. Timing

Use a frame-based render loop.

Target:

```text
30 FPS preferred
60 FPS acceptable where inexpensive
```

Animations should be based on elapsed time rather than frame count.

Example:

```text
progress = elapsed / duration
```

Never assume that every frame will render.

---

# 5. Standard Duration Ranges

Use a small shared timing vocabulary.

### Instant feedback

```text
40–100 ms
```

Use for:

- button press feedback
- tiny flashes
- selection reaction
- keystroke confirmation
- micro-shake

### Fast transition

```text
100–200 ms
```

Use for:

- focus changes
- highlights
- indicators
- small reveals
- selection movement

### Standard transition

```text
180–350 ms
```

Use for:

- panels entering
- rows reorganizing
- content appearing
- dialogs opening
- tab transitions

### Dramatic transition

```text
350–700 ms
```

Use sparingly for:

- major mode changes
- important successful operations
- first-time reveals
- application-level state changes

Routine navigation should rarely exceed 300 ms.

---

# 6. Easing

Linear interpolation should rarely be used for visible UI movement.

Provide at least:

```text
easeOutCubic
easeInOutQuad
easeOutBack
easeInCubic
```

Recommended defaults:

### Movement

```text
easeOutCubic
```

### Opening / appearing

```text
easeOutBack
```

with subtle overshoot.

### Closing / disappearing

```text
easeInCubic
```

### Reorganization

```text
easeInOutQuad
```

Overshoot should be modest.

The UI should feel energetic, not rubbery.

---

# 7. Animation Primitives

Build reusable primitives instead of implementing each animation independently.

Recommended primitives follow.

## Move

Moves an element between two positions.

```text
MOVE
```

Uses:

- cursor-like selection objects
- rows
- panels
- indicators
- reordered items

---

## Slide

Moves an element into or out of a clipped region.

```text
SLIDE_IN
SLIDE_OUT
```

Prefer short travel distances.

A panel does not need to originate off-screen. Moving 2–5 cells often provides enough visual information.

---

## Reveal

Changes the visible region rather than moving the object.

```text
REVEAL_HORIZONTAL
REVEAL_VERTICAL
```

This is especially useful in terminals.

Example:

```text
│
├───
├────────
┌──────────────┐
```

Use for:

- panels
- menus
- result sections
- expandable areas
- command output

---

## Collapse

Reverse of reveal.

The interface should visibly indicate where disappearing information went when possible.

---

## Pulse

Briefly increases brightness, border weight, or visual emphasis.

Example:

```text
normal
→ bright
→ bold/bright
→ normal
```

Use for:

- success
- newly updated values
- selected objects
- operation completion

---

## Flash

A very short foreground or background color change.

Use carefully.

Best for:

- success
- errors
- destructive actions
- incoming information

Usually 50–150 ms.

---

## Shake

Apply short positional jitter.

Example:

```text
x
x+1
x-1
x+1
x
```

Use for:

- invalid actions
- rejected input
- failed operations

Keep amplitude around 1 terminal cell.

Avoid long shaking sequences.

---

## Pop

Simulate scale through representation changes, border changes, or small positional expansion.

For example:

```text
thin
→ compact
→ full
→ slightly emphasized
→ settled
```

Terminals cannot scale arbitrary objects smoothly, so scaling should generally be represented symbolically.

---

## Dim / Brighten

Simulate opacity using terminal color.

Example:

```text
dark gray
→ gray
→ bright gray
→ white
```

With true-color terminals, interpolate RGB values.

Use this instead of attempting literal alpha transparency.

---

## Glyph Morph

Swap glyphs over several frames.

Example:

```text
·
*
✦
*
·
```

or:

```text
░
▒
▓
█
```

Useful for:

- loading
- appearing
- transformation
- progress
- subtle effects

---

## Type / Decode Reveal

Reveal textual information incrementally.

Two useful variants:

### Typewriter

```text
R
RE
RES
RESU
RESULT
```

### Decode

```text
R_5?L7
RE$U_T
RESU_T
RESULT
```

Use decode effects sparingly and only when appropriate to the visual language of the application.

Do not make users wait through long text animations.

---

# 8. Entering Elements

New UI elements should generally not appear fully formed in a single frame.

Use one or more of:

- short slide
- clipped reveal
- brightness ramp
- pop
- border construction
- glyph transition

Recommended default:

```text
duration: 180–250 ms
motion: 1–3 cells
easing: easeOutCubic
brightness: dim → normal
```

---

# 9. Exiting Elements

Exits should normally be faster than entrances.

Recommended:

```text
duration: 100–180 ms
```

Possible behaviors:

- collapse
- slide a few cells
- dim
- clip closed

Avoid elaborate exit animations unless the disappearance is itself significant.

---

# 10. Layout Changes

When elements move because the layout changes, animate them toward their new location rather than redrawing the entire layout instantly.

For example:

```text
before

[A]
[B]
[C]

after removing B

[A]
[C]
```

Prefer:

```text
[B] disappears
[C] moves upward
layout settles
```

This preserves spatial continuity.

The same applies to:

- sorting
- filtering
- expanding
- collapsing
- inserting rows
- moving items between regions

---

# 11. Staggering

When several related objects change at once, do not necessarily animate all of them on the exact same frame.

Use small stagger intervals:

```text
20–60 ms
```

Example:

```text
item 1 begins
30 ms later item 2
30 ms later item 3
```

Staggering makes grouped transitions legible.

Keep total stagger duration short enough that the user does not feel forced to watch a sequence finish.

---

# 12. Anticipation

Important actions may briefly move or visually react in the opposite direction before proceeding.

Example:

```text
normal
→ compress
→ move/open
→ settle
```

In terminal coordinates:

```text
x = 20
x = 19
x = 27
x = 26
```

The first tiny movement creates anticipation.

Use only for important actions.

---

# 13. Overshoot and Settle

Elements should occasionally move slightly past their destination and return.

Example:

```text
target x = 30

27
29
31
30
```

This is especially effective for:

- dialogs
- major panels
- focused controls
- important results

Overshoot should generally be about one terminal cell.

---

# 14. Selection and Focus

Moving focus should have visible continuity.

Avoid:

```text
highlight disappears from A
highlight instantly appears on B
```

Prefer:

- moving selection marker
- short highlight interpolation
- border movement
- one-cell slide
- brief destination pulse

Focus animations should be fast:

```text
80–160 ms
```

Repeated keyboard navigation must remain responsive.

If the user moves rapidly, animations should retarget rather than queue.

---

# 15. Expanding and Collapsing Content

Expandable content should visibly emerge from its parent.

Recommended expansion sequence:

```text
parent reacts
→ border opens
→ content area grows
→ text becomes visible
→ settle
```

Recommended collapse:

```text
content dims
→ region shrinks
→ border closes
```

The parent should remain spatially stable when practical.

---

# 16. Loading and Processing

Avoid generic spinners as the only sign of activity when the UI can communicate more.

Possible techniques:

- moving highlight across the active region
- animated border
- pulsing status text
- glyph cycling
- dot sequences
- progressing scan line

Examples:

```text
PROCESSING
PROCESSING.
PROCESSING..
PROCESSING...
```

or:

```text
░░░░░
▒░░░░
▓▒░░░
█▓▒░░
```

Animations should indicate that the process remains active without becoming visually dominant.

---

# 17. Success Feedback

Successful actions should usually produce a short response.

Possible sequence:

```text
target pulses
→ confirmation symbol appears
→ symbol fades
→ target returns to normal
```

Example:

```text
[ saved ]
[✓ saved]
[✓ SAVED]
[ saved ]
```

Duration:

```text
150–400 ms
```

Do not use large effects for routine operations.

---

# 18. Error Feedback

Errors need strong but short feedback.

Recommended:

```text
target shakes
→ error color flashes
→ error message appears
```

Do not repeatedly flash.

Avoid animations that obscure the actual error text.

---

# 19. Notifications and Incoming Information

New information should visually originate from its logical source when possible.

For example:

```text
background task finishes
→ status indicator reacts
→ notification enters
```

Do not abruptly spawn unrelated content in the center of the screen without context.

---

# 20. Borders as Animation Surfaces

Terminal borders are useful animation primitives.

An inactive panel:

```text
┌──────────────┐
│              │
└──────────────┘
```

can become active:

```text
╔══════════════╗
║              ║
╚══════════════╝
```

Possible border states:

```text
thin
heavy
double
partial
bright
dim
animated construction
```

Use border changes to communicate hierarchy rather than decorating every panel.

---

# 21. Color Animation

If true-color output is supported, interpolate colors over time.

If not, use discrete palette stages.

Example:

```text
dark gray
gray
white
bright white
```

Color changes can substitute for opacity.

Avoid rapidly cycling hues.

Avoid large full-screen flashes.

---

# 22. Terminal-Native Particles

Particles may be used for rare emphasis moments.

Suitable glyphs include:

```text
·
•
*
+
✦
✧
⋆
×
```

A particle contains:

```text
x
y

vx
vy

glyph
lifetime
brightness
```

Particles should usually live:

```text
150–600 ms
```

Good uses:

- completion
- successful transformation
- major reveal
- transition between major modes

Do not use particles continuously.

---

# 23. Fine-Grained Terminal Effects

Where useful, Unicode block characters can simulate sub-cell motion.

Examples:

```text
▀
▄
▌
▐
█
```

Braille characters may provide even finer resolution.

These techniques are best reserved for:

- particles
- indicators
- abstract visual effects
- charts
- transitions

Do not make core text difficult to read.

---

# 24. Text Animation

Text itself may animate through:

- incremental reveal
- brightness
- temporary emphasis
- character substitution
- brief displacement
- underline/bold transitions

Avoid animating long paragraphs.

Important text should become readable quickly.

A good rule:

```text
animation may introduce text
but should not delay access to information
```

---

# 25. Number and Value Changes

Numeric values should visually acknowledge significant changes.

Possible techniques:

- animated interpolation
- short count-up
- brightness pulse
- directional indicator
- temporary delta

Example:

```text
42
51
67
78
83
```

For large jumps, do not animate every integer.

Use eased interpolation.

Routine rapidly changing metrics may update directly unless animation improves comprehension.

---

# 26. Layering

Animations sometimes overlap.

Implement a basic layer or z-index system.

For example:

```text
0 background
10 normal content
20 selected content
30 overlays
40 modal
50 animation effects
60 notifications
```

Temporary animation objects should not permanently affect application layout.

---

# 27. Interruptibility

All animations should fall into one of three categories:

### Retargetable

Example:

```text
selection movement
scrolling
panel resizing
```

If the target changes, update the animation destination.

### Replaceable

Example:

```text
highlight pulse
shake
```

A newer animation replaces the previous one.

### Nonessential

Example:

```text
particles
decorative reveal
```

These may simply be canceled if the UI needs to respond to a new action.

Avoid long animation queues.

---

# 28. Animation Composition

Complex effects should be built by combining primitives.

Example:

```text
OPEN_PANEL =
    reveal vertical
  + move upward 2 cells
  + brightness ramp
  + border emphasis
```

Example:

```text
SUCCESS =
    pulse target
  + flash foreground
  + transient symbol
```

Example:

```text
ERROR =
    shake target
  + brief red flash
  + reveal message
```

Avoid implementing every animation as bespoke rendering logic.

---

# 29. Timeline API

Provide a small declarative API.

Conceptually:

```text
animate({
    target,
    duration,
    easing,
    from,
    to
})
```

Support delays:

```text
animate({
    target,
    delay: 40,
    duration: 180,
    ...
})
```

Support sequences:

```text
sequence([
    animationA,
    animationB,
    animationC
])
```

Support parallel groups:

```text
parallel([
    animationA,
    animationB
])
```

Support staggered collections:

```text
stagger(items, 30, animation)
```

Exact syntax should match the application's language and architecture.

---

# 30. Semantic Animation Events

Application code should trigger semantic events rather than low-level effects.

Prefer:

```text
animations.trigger("panel-open", panel)
animations.trigger("operation-success", target)
animations.trigger("invalid-action", target)
animations.trigger("item-inserted", item)
```

instead of:

```text
shake(target)
flash(target)
move(target)
```

The animation system can map semantic events to visual behavior.

This allows the visual language to evolve without rewriting application logic.

---

# 31. Recommended Default Animation Vocabulary

Implement a small standard set first:

```text
enter
exit

focus
blur

open
close

expand
collapse

insert
remove
reorder

success
warning
error

processing-start
processing-stop

value-change

notification-enter
notification-exit
```

Most of the application's animation needs should be expressible through these events.

---

# 32. Rendering Strategy

Avoid clearing and repainting the entire terminal each frame when possible.

Maintain:

```text
previousFrame
currentFrame
```

Compare the two and output only changed cells or changed spans.

Use:

- alternate screen buffer
- hidden cursor while rendering
- ANSI cursor positioning
- ANSI true color when supported
- synchronized terminal output where available
- buffered writes

Render a complete logical frame before sending terminal output.

This minimizes flicker and partial-frame artifacts.

---

# 33. Animation and Application State

Animated values must not become the source of truth.

Example:

Application state:

```text
panel.isOpen = true
```

Animation state:

```text
panel.visualHeight = 0.0 → 12.0
```

If animation is interrupted, the logical state remains correct.

This separation is mandatory.

---

# 34. Reduced Motion

Provide a configuration option such as:

```text
animations = full
animations = reduced
animations = off
```

Reduced motion should:

- remove shaking
- remove large movement
- remove particles
- shorten transitions
- preserve essential state-change feedback

Off should render the final state immediately.

Application behavior must remain identical.

---

# 35. Performance

Animation must not materially increase CPU usage when the interface is idle.

Prefer an event-driven renderer:

```text
idle:
    no continuous frame loop

animation active:
    render at target FPS

animation finishes:
    return to idle
```

Continuous animation may justify an ongoing frame loop only while it is visible.

---

# 36. Animation Density

Not every interaction should trigger a dramatic effect.

Use three levels.

## Level 1: Micro Feedback

Very common.

Examples:

```text
selection
focus
keypress
toggle
```

Duration:

```text
50–150 ms
```

---

## Level 2: Interface Transition

Moderately common.

Examples:

```text
panel open
row insert
section expansion
modal
```

Duration:

```text
150–350 ms
```

---

## Level 3: Emphasis Event

Rare.

Examples:

```text
major completion
significant transformation
important result
major mode change
```

Duration:

```text
300–700 ms
```

Reserve visual intensity for Level 3 events.

This makes important moments actually feel important.

---

# 37. Visual Hierarchy During Animation

At any moment, the user should be able to identify the primary animated object.

Avoid:

```text
panel moving
+ status flashing
+ border pulsing
+ text scrambling
+ particles
+ unrelated spinner
```

all at once.

Prefer one dominant effect with one or two supporting effects.

---

# 38. Motion Distance

Terminal motion should generally be short.

Typical:

```text
1–5 cells
```

Long-distance movement often looks crude because of terminal resolution.

Use clipping, fading, or intermediate representations for larger transitions.

---

# 39. Animation Testing

Test at:

```text
slow terminal
fast terminal
SSH
different terminal sizes
different refresh rates
true-color terminal
256-color terminal
```

Check specifically for:

- flicker
- tearing
- input latency
- unreadable intermediate frames
- queued animations
- layout corruption
- ghost characters
- cursor artifacts

Add a debug setting that slows animation speed significantly.

Example:

```text
animationSpeed = 0.25x
```

This makes timing and compositing errors easier to inspect.

---

# 40. Implementation Order

Do not attempt to animate the entire application immediately.

Implement in roughly this order:

### Phase 1

Build:

```text
animation clock
timeline
easing
interpolation
render invalidation
```

### Phase 2

Add:

```text
focus movement
panel open/close
expand/collapse
item insert/remove
```

### Phase 3

Add:

```text
pulse
flash
shake
value change
status transitions
```

### Phase 4

Add:

```text
stagger
overshoot
glyph morphing
border animation
particles
special emphasis effects
```

### Phase 5

Review the application and replace inconsistent one-off animations with shared semantic animation events.

---

# 41. Default Design Language

Unless a specific part of the interface requires something else, use these defaults:

```text
movement:
    short
    eased
    120–250 ms

entrance:
    slight movement
    clipped reveal
    dim → normal

exit:
    faster than entrance
    dim or collapse

focus:
    very fast
    retargetable

success:
    pulse + brief brightening

error:
    one-cell shake + brief color flash

layout changes:
    preserve spatial continuity

major events:
    anticipation + action + overshoot + settle
```

---

# 42. Definition of Done

The animation system is successful when:

- the UI remains fully usable with animation disabled
- input never waits unnecessarily for animation
- important actions have visible cause and effect
- layout changes preserve spatial continuity
- repeated navigation remains fast
- animation vocabulary is consistent across the application
- major events feel more significant than routine events
- animations use terminal-native techniques rather than poorly imitating GUI animation
- the renderer does not visibly flicker
- animations can be interrupted, retargeted, or canceled safely
- the codebase contains reusable animation primitives rather than scattered timing hacks

The target experience should feel responsive, tactile, and intentional. The interface should appear to react to the user rather than merely redraw after them.