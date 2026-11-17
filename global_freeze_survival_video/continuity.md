# Continuity Notes

## User-supplied style references
- Primary file: `refs/style_reference.jpg`.
- Supplemental files: `refs/user_reference_1.png`, `refs/user_reference_2.png`, and `refs/user_reference_3.png`.
- All supplied images are for art-style and character inspiration only; never use their scenes as spatial backgrounds, compositions, or camera templates. Create each environment and framing dynamically for its narration beat.

## Approved master anchor
- File: `refs/style_test_v2.png`.
- User selected option 2 of the regenerated style-test pair. This is the approved style anchor for frame generation.
- The selected image depicts a simple expressive, pale round-faced survivor with tousled dark hair and a practical brown hooded winter coat; strong organic ink lines and crosshatching; textured paper; warm cream interior against a deep navy, snowbound city exterior.

## Final Art-Style & Character Invariants
This exact block is the verbatim prefix for every `visual_prompt` in `visuals.csv`:

> Hand-drawn 2D graphic-novel illustration with bold organic black ink contours, loose crosshatching, visible paper grain, and soft textured shading; recurring survivor has a simple pale round face, large dark eyes, tousled dark-brown hair, and a practical brown hooded winter coat; warm cream-and-ochre interiors contrast with deep navy-blue cold exteriors.

## Approved anchor prompt — selected option 2

> Use all four supplied reference images only for shared art-style and character-design cues; do not copy any referenced environment, object placement, poses, lighting setup, or camera composition. Create a distinct landscape 16:9 animated-story frame in a modern high-rise apartment during a worldwide freeze: a simple expressive round-faced survivor with tousled dark hair and a practical brown winter coat stands at a frost-rimmed window, looking down toward a snow-buried city street at blue pre-dawn. Blend clean readable cartoon silhouettes and expressive minimal facial features with confident black ink contours, hand-drawn paper grain, subtle crosshatching, muted warm cream and ochre interior colors contrasted with deep navy exterior shadows. Keep the character’s face and hair design consistent; let the apartment and city be entirely new, contemporary, and clearly cold. Mid-shot from a low three-quarter angle inside the apartment, a little window condensation and frost in foreground, no cave, campfire, sofa scene, wall display, or plant from references. No text, captions, watermarks, collage, split panels, or extra people.

## Master prompt formula
Every frame prompt is the verbatim approved art-style/character block above plus dynamic camera framing and action matching its `moment_text`. Consecutive frames must vary camera framing and environmental focus; do not reuse a static background. The anchor image is a style/character guide only, never a spatial template.

## Rejected test
The first style-test pair was declined; no image was saved.

## Content moderation
No blocked words or replacements logged yet.
