# Skill Transfer: How to Create High-Quality Draw.io-Style SVG/HTML Diagrams with LLM Agents

This guide documents the complete end-to-end process used to design, implement, and iteratively refine the three high-quality architecture and sequence diagrams (`harness_agent_architecture.html`, `user_touchpoints.html`, and `high_level_architecture.html`). 

You can use this document to transfer this "skill" to other developers or AI agents, enabling them to produce consistent, professional-grade diagrams purely through code.

---

## Phase 1: Conceptualization & Requirements Analysis

Before writing any HTML/SVG, the system architecture and the story it needs to tell must be fully understood.

1. **Ingest Context:** Read the core documentation (e.g., `guidebook.md`, `PROJECT_OVERVIEW.md`). Identify the main actors, components, and design patterns (e.g., The 5 Pillars, ReAct Loop, State Machine, HITL).
2. **Determine the Diagram Type:**
   - **Component/Architecture Diagram:** Focuses on boundaries, static relationships, and containment (e.g., `harness_agent_architecture.html`, `high_level_architecture.html`).
   - **Sequence Diagram:** Focuses on time, lifelines, message passing, and asynchronous events (e.g., `user_touchpoints.html`).
3. **Map the Narrative:** Decide on the visual flow. 
   - *Example:* For the High-Level Architecture, the narrative was "User -> Gateway -> Core -> Environment". Therefore, a Left-to-Right horizontal layout was chosen.

## Phase 2: Planning & Coordinate Math (The "Mental Canvas")

Always use a "Plan Mode" or write a draft implementation plan before coding. Because an LLM cannot physically "see" the canvas, you must rely on strict mathematical logic to prevent overlaps and ensure a clean, readable layout.

1. **Define Objective & List Elements:** Explicitly list all visual blocks needed (e.g., Left: UI, Middle: API, Center: Core, Right: DB).
2. **Establish Styling Rules:** Define color palettes (e.g., Blue for core, Green for execution) and shapes (rounded rectangles, drop shadows).
3. **Apply the Grid System & Bounding Box Math:**
   - Use a standard unit (e.g., 50px or 100px). Snap all `x`, `y`, `width`, and `height` values to this grid.
   - For every component, calculate its exact boundaries: `right_edge = x + width` and `bottom_edge = y + height`.
   - Ensure the next adjacent component starts at `x = right_edge + minimum_margin` (e.g., at least 100px padding).
4. **Define Standard Connection Ports:** Standardize where lines attach to boxes to make routing calculations predictable.
   - Top-Center: `(x + width/2, y)`
   - Bottom-Center: `(x + width/2, y + height)`
   - Left-Middle: `(x, y + height/2)`
   - Right-Middle: `(x + width, y + height/2)`
5. **Reserve Routing Lanes ("Highways"):**
   - Dedicate specific empty rows or columns *exclusively* for lines (`<path>`). Do not place any boxes in these zones.
   - *Horizontal Lane:* Keep a band (e.g., `y=250` to `y=320`) empty to allow lines to safely traverse left-to-right across the diagram.
   - *Vertical Lane:* Keep a band (e.g., `x=700` to `x=750`) empty for top-to-bottom connections.
6. **Orthogonal (Manhattan) Routing Logic:**
   - Strictly use 90-degree lines (`L` commands) instead of diagonals. Diagonal lines unpredictably cut through bounding boxes.
   - Example: Avoid `M 200 200 L 400 400`. Instead, route via a lane: `M 200 200 L 300 200 L 300 400 L 400 400`.
   - *Parallel Offset:* If multiple lines share the same routing lane, offset their coordinates by 10-20px (e.g., Line A routes down `x=300`, Line B routes down `x=320`) so they never overlap.
7. **Draft the Canvas Size:** Estimate the total `width` and `height` required (`<svg width="..." height="...">`) after stacking up all calculated bounding boxes and routing lanes.

## Phase 3: The SVG/HTML Implementation Framework

We use raw SVG embedded in HTML. This provides the best mix of version control (it's text), rendering quality (infinitely scalable), and Draw.io aesthetics without needing the actual software.

### 1. The HTML/CSS Wrapper
Start with a standard HTML boilerplate. Use CSS to create a container that looks like a drawing canvas.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <style>
        body { background-color: #f6f8fa; padding: 40px; display: flex; justify-content: center; }
        .diagram-container {
            background-color: #ffffff;
            border-radius: 12px;
            box-shadow: 0 12px 40px rgba(0,0,0,0.08);
            padding: 30px;
        }
        svg { display: block; }
        /* Add typography and reusable stroke/fill classes here */
    </style>
</head>
<body>
    <div class="diagram-container">
        <svg width="1800" height="900" xmlns="http://www.w3.org/2000/svg">
            <!-- Diagram content goes here -->
        </svg>
    </div>
</body>
</html>
```

### 2. SVG Definitions (`<defs>`)
Always define reusable assets first. This makes the code cleaner.
- **Markers (Arrows):** Essential for connecting lines. Create different colors if needed.
- **Gradients:** Use linear gradients (`<linearGradient>`) to give boxes a professional, 3D "Draw.io" feel.

```xml
<defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#24292f"/>
    </marker>
    <linearGradient id="blueGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#dae8fc"/><stop offset="100%" stop-color="#c4d6f0"/>
    </linearGradient>
</defs>
```

### 3. Layering & Drawing Strategy
Draw from the background to the foreground (SVG uses painter's algorithm).

1. **Background Boundaries:** Draw large `<rect>` elements with low opacity (`fill="rgba(...)"`) and dashed strokes (`stroke-dasharray`) to group related components.
2. **Lifelines (For Sequence Diagrams):** Draw vertical `<line>` elements from top to bottom.
3. **Boxes & Components:** Draw the core nodes using `<rect rx="6">` (rounded corners) and apply gradient URLs (`fill="url(#blueGrad)"`).
4. **Text:** Add `<text>` elements. 
   - *Crucial:* Pay strict attention to `x` and `y` coordinates. Use `text-anchor="middle"` when centering text inside a box. Use multiple `<tspan>` or `<text>` lines for multiline paragraphs.
5. **Connections (Paths):** Use `<path d="M X1 Y1 L X2 Y2" />` for lines.
   - For orthogonal routing (lines with 90-degree corners), use multiple `L` commands: `M 100 100 L 150 100 L 150 200 L 200 200`.
   - Apply `marker-end="url(#arrow)"` to add arrowheads.

## Phase 4: Iterative Refinement & Alignment

SVG drawing via LLM is rarely perfect on the first try. It requires meticulous coordinate adjustments based on visual feedback or logical reviews.

1. **Fixing Arrow Directions:** 
   - Check the semantic meaning. Does "Observe" mean data returning from a tool to the agent? If so, the path must be drawn from Right to Left (`M RightX Y L LeftX Y`).
2. **Debugging Overlaps (Collision Resolution):**
   - *Line-to-Box Collision:* If a line awkwardly crosses through a box, re-route it by adding an extra 90-degree turn (`L` command) to push it into a reserved "Routing Lane" (as defined in Phase 2).
   - *Line-to-Line Collision:* If two arrows or paths lie directly on top of each other, apply a *Parallel Offset*. Shift one path's orthogonal axis by +20px and the other by -20px.
   - *Example:* If two lines share a vertical return path `L 900 750`, adjust them to `L 900 750` and `L 920 750` respectively.
3. **Canvas Sizing:** If components look squashed, increase the `<svg width="..." height="...">` and physically translate the `x` coordinates of the elements on the right side.
4. **Aesthetics:** Remove development artifacts (like the grid background) once alignment is verified to provide a clean, production-ready look. Add descriptive legends or captions at the bottom.

## Phase 5: "Hand-Drawn" Aesthetic Guidelines (The Digital Whiteboard)

When requested to create diagrams with an approachable, human-centric "whiteboard sketch" feel (like Excalidraw), apply these specific aesthetic and structural rules on top of the standard framework.

### 1. Typography & Styling
*   **Font Family**: Import and use Google Fonts like `'Kalam', cursive` to provide a natural, slightly irregular handwriting style.
*   **Font Weights**: Use standard (`400`) for descriptive text and bold (`700`) for titles and emphasis to create visual hierarchy.
*   **Soft Pastels**: Avoid harsh standard colors. Use soft, low-saturation pastel gradients for main component boxes (e.g., Soft Orange `#ffedd6` to `#ffe1ba`, Pale Yellow `#fff8d6` to `#ffeeb3`, Soft Cyan `#e0fcff` to `#baffff`).
*   **Soft Shadows**: Apply a subtle, semi-transparent drop shadow (`feDropShadow` with 8% opacity) to floating elements to give them depth against a paper-like background color (e.g., `#fdfbf7`).
*   **Rounded Corners**: Apply generous border radiuses (e.g., `rx="10"` or `rx="15"`) to all rectangles.
*   **Marker Style Arrows**: Redefine arrow markers (`<marker>`) using a specific SVG path (e.g., `d="M 0 1 L 9 5 L 0 9 z"`) to make them look wider and softer, mimicking the stroke of a whiteboard marker.

### 2. Layout & Semantic Highlighting
*   **X/Y Symmetry & Banding**: Even for informal styles, use a strict logical grid. Place elements in clear horizontal bands (e.g., all orchestrators at `y=120`, all agents at `y=440`) and mirror elements around the center axis for visual balance.
*   **Explicit Workspaces**: Use large, transparent `<rect>` elements with thick, dashed borders to explicitly define isolated "Scopes" or "Workspaces".
*   **State / Garbage Collection Callouts**: When depicting memory isolation or data flow, use high-visibility dashed boxes (often red/pink) with clear text like "Working Memory Destroyed" or "Garbage Collected" to emphasize state lifecycles.
*   **Bottlenecks/Filters**: Visually position transformation layers (like State Filters) as unavoidable choke points to reinforce that data must pass through them.

## Summary Checklist for Diagram Generation
- [ ] Requirements fully analyzed.
- [ ] Layout strategy defined (Horizontal vs. Vertical, Sequence vs. Component).
- [ ] HTML/CSS wrapper with `<defs>` (Gradients, Arrows) setup.
- [ ] Background boundaries drawn first.
- [ ] Components (Boxes) drawn with consistent spacing.
- [ ] Text aligned carefully within components.
- [ ] Connecting lines routed cleanly, avoiding intersections where possible.
- [ ] Semantic review of arrow directions and data flow.
- [ ] Final aesthetic pass (remove grids, adjust padding, add titles).