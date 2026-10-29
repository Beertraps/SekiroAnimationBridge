# Interchange formats

The bridge's game-specific code ends where these files begin. A game adapter decodes the game's own files into them; Blender, the skeleton preview, the retarget add-on and the export read only these files. A new game therefore needs an adapter and, when the game has a format the existing decoders cannot read, a decoder that writes these files. Nothing downstream changes.

JSON Schemas for each format are in [`standalone/schemas/`](../standalone/schemas). `standalone/games/interchange.py` checks a document against them without third-party packages, and `standalone/tests/test_interchange.py` checks the synthetic documents of every test against them.

| File | Written by | Read by | Schema |
| --- | --- | --- | --- |
| Motion JSON | a decoder, then the bridge adds the source | Blender import, export, retarget add-on, preview | [`motion.schema.json`](../standalone/schemas/motion.schema.json) |
| Character manifest | the adapter's character step | Blender import | [`character.schema.json`](../standalone/schemas/character.schema.json) |
| Model arrays (`.npz`) | the adapter's character step | Blender import | listed below |
| Textures | the adapter's character step | Blender import | PNG files |
| Preview JSON | the decoder's preview mode, or `clip_preview.computed` | `ui/preview.js` | [`preview.schema.json`](../standalone/schemas/preview.schema.json) |
| Package manifest (`package.json`) | the author of a game package | the bridge's package loader | [`package.schema.json`](../standalone/schemas/package.schema.json) |
| Source catalog | a game package's `scan` and `inventory` | the bridge, the Import page | [`catalog.schema.json`](../standalone/schemas/catalog.schema.json) |

Game packages, which add the games of other engines, are described in [PACKAGES.md](PACKAGES.md). The bridge checks everything a package returns against these schemas before it uses it.

## Source space

Every game stores positions and rotations in its own axis convention and unit. The interchange keeps them in that space and says which space it is, so a decoder never converts axes and Blender converts once, in one place.

- `basis` is a 3×3 matrix *B*, written as three rows. It maps a vector from source space to Blender space: *v*<sub>Blender</sub> = `unitScale` · *B* · *v*<sub>source</sub>. *B* must be a signed permutation: each row and each column holds exactly one 1 or −1.
- `unitScale` converts the source unit to metres. It applies to translations, root-motion locations and mesh positions, not to rotations or scale.

From these two values:

| Value | Conversion to Blender |
| --- | --- |
| Translation, position | `unitScale · B · t` |
| Scale | the components reordered like *B*'s columns, without signs |
| Quaternion (x, y, z, w) | w unchanged, (x, y, z) becomes `det(B) · B · (x, y, z)` |
| Normal | `B · n` |
| Triangle | winding reversed when `det(B) = −1` |
| Bone rest matrix *M* | `C · M · C⁻¹` with `C = unitScale · B` |

Known spaces:

| Engine | `basis` | `unitScale` | Meaning |
| --- | --- | --- | --- |
| FromSoftware (Havok, FLVER) | `[[1,0,0],[0,0,1],[0,1,0]]` | 1 | Y up, left-handed: swap Y and Z, which reflects |
| RE Engine | `[[1,0,0],[0,0,-1],[0,1,0]]` | 1 | Y up, right-handed: +90° about X, no reflection |

A document without `basis` uses the FromSoftware space. This keeps every motion JSON and manifest written before version 2 valid, including the ones embedded in existing `.blend` files. The conversion code is `standalone/games/space.py`; with the FromSoftware basis it gives exactly the results of the bridge's earlier, fixed Y/Z swap.

## Motion JSON

One decoded clip and the skeleton it plays on. `format` is `"sekiro-animation-bridge"`.

| Field | Type | Meaning |
| --- | --- | --- |
| `formatVersion` | 1 or 2 | 2 adds `source`, `basis` and `unitScale` |
| `clip` | string | file name of the clip, used for names in Blender |
| `skeletonName` | string | must equal `skeleton.name` |
| `skeleton.boneCount` | integer | number of bones |
| `skeleton.bones[]` | objects | `index`, `name`, `parent` (−1 for a root), local rest `translation` [3], `rotation` [x, y, z, w], `scale` [3]. Parents come before their children. |
| `frameCount` | integer | number of samples in `frames` |
| `frameRate` | number | samples per second |
| `duration` | number | seconds; normally `(frameCount − 1) / frameRate` |
| `trackCount` | integer | number of animated bones |
| `trackBoneIndices[]` | integers | the bone each track animates; −1 for a track without a bone |
| `trackNames[]` | strings | the track's name in the source file |
| `frames[f][t]` | objects | local `translation`, `rotation`, `scale` of track *t* at sample *f* |
| `compression` | string | the source's encoding: `interleaved`, `spline`, `re-mot` |
| `blockCount` | integer | spline blocks; 0 otherwise |
| `rootMotion` | null or `[[x, y, z, yaw], …]` | one sample per frame; yaw turns about the source's up axis |
| `rootUp`, `rootForward` | null or [4] | Havok reference-frame axes |

Version 2 fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `source.engine` | string | `fromsoft`, or the ID of the game package that read the file, such as `re_engine` |
| `source.game` | string | the game's ID from the registry, such as `sekiro` or `dmc5` |
| `source.container` | string | the file type the clip came from: `hkx`, `motlist`, `mot` |
| `source.version` | integer or string | the container's version |
| `source.archive`, `source.member`, `source.index` | | where in the source the clip was found |
| `basis`, `unitScale` | | the source space, see above |

The bridge adds `game`, `archive` and `member` at the top level for every game, and `sourceHavok` for FromSoftware games. Export reads them to write the clip back.

Values are dense samples: a decoder evaluates its format's curves at every frame. Components a source does not animate take the bone's rest value.

## Character manifest

`character.json`: the models of a character, their materials and the paths of their arrays and textures.

| Field | Meaning |
| --- | --- |
| `version` | 4 or 5 |
| `game` | the game's ID |
| `models[]` | `name`, `source` (the file it came from), `data` (path of its `.npz`), `materials[]`, `stats`, `attachment` (a weapon's socket, or null) |
| `models[].materials[]` | `name`, `mtd` (the source's shader or material definition), `albedo`, `normal`, `emissive`, `tint` (each null or an image: `path`, `linear`, `uv`, `scale`, `stem`), `samplers[]`, `alpha`, `color` |
| `warnings[]` | notices for the activity log |
| `texture_count` | number of images written |

Version 5 adds:

| Field | Meaning |
| --- | --- |
| `basis`, `unitScale` | the models' source space |
| `boneRotation` | `euler_xzy` (default): `bone_rotations` holds FLVER Euler angles. `quaternion`: `bone_quaternions` holds [x, y, z, w]. |
| `models[].materials[].normal.convention` | `directx` (default, green channel down) or `opengl` |
| `models[].materials[].normal.channels` | `xy` (default): the image's red and green hold X and Y and Z is rebuilt. `xyz`: the image holds all three. |
| `models[].materials[].family` | the name Blender gives the material before ` / `, such as `Devil May Cry 5`; `FromSoftware` when absent |
| `models[].materials[].opacity` | null or an image whose `channel` (`R`, `G` or `B`) cuts the material out, such as red of an RE Engine ATOS map |
| `models[].materials[].opacityValue` | a fixed opacity from 0 to 1, for overlays the preview cannot shade, such as eye wetness |
| image `packedAlpha` | true when the image's alpha holds other data (metalness, roughness): Blender reads it as channel-packed, so it does not darken the color |
| `models[].role` | the part's label in Blender, such as `Body`, `Head` or `Hair`; FromSoftware models are labelled by their file prefix |

All version 5 fields are optional except `version`; a reader treats a missing one as its default, so the FromSoftware characters stay version 4.

## Model arrays

One compressed NumPy archive per model, loaded with `allow_pickle=False`.

| Array | Shape, type | Meaning |
| --- | --- | --- |
| `positions` | (n, 3) float32 | vertex positions in source space |
| `normals` | (n, 3) float32 | vertex normals; zeros when the source has none |
| `uvs` | (n, 2) float32 | the first UV set; V points down as in DirectX |
| `uv_0`, `uv_1`, … | (n, 2) float32 | every UV set; materials name theirs by number |
| `bone_indices` | (n, 4) int32 | indices into `bone_names` |
| `bone_weights` | (n, 4) float32 | weights summing to 1 |
| `faces` | (m, 3) int32 | triangles in the source's winding |
| `face_materials` | (m,) int32 | index into the model's materials |
| `vertex_materials` | (n,) int32 | the material of the submesh each vertex belongs to |
| `bone_names` | (b,) str | the model's bones |
| `bone_parents` | (b,) int32 | parent index, −1 for a root |
| `bone_translations` | (b, 3) float32 | local rest translation |
| `bone_rotations` | (b, 3) float32 | local rest rotation as Euler XZY (manifest `boneRotation` `euler_xzy`) |
| `bone_quaternions` | (b, 4) float32 | local rest rotation as [x, y, z, w] (manifest `boneRotation` `quaternion`) |
| `bone_scales` | (b, 3) float32 | local rest scale |
| `material_names` | (k,) str | one per material |

## Preview JSON

The skeleton preview's joint positions, gzipped by `clip_preview.preview`.

| Field | Meaning |
| --- | --- |
| `clip`, `skeleton` | names |
| `frameCount`, `frameRate`, `duration` | as in the motion JSON |
| `frameStep` | every `frameStep`th frame is included |
| `bones[]`, `parents[]` | the skeleton |
| `tracks` | number of animated bones |
| `positions[f]` | world positions, x, y, z per bone, in source space |
| `detached[]` | bones far from the body, hidden by default |
| `root` | null or `[[x, y, z, yaw], …]` |
| `basis`, `unitScale` | optional source space; the FromSoftware space when absent |

## Versions

| Format | Version | Change |
| --- | --- | --- |
| Motion JSON | 1 | first version |
| Motion JSON | 2 | `source`, `basis`, `unitScale` |
| Character manifest | 4 | current FromSoftware manifest |
| Character manifest | 5 | `basis`, `unitScale`, `boneRotation`, normal-map convention |
| Preview JSON | 3 | current; `basis` and `unitScale` are optional additions |

Readers accept every version in this table. Writers write the newest version they need: the FromSoftware path keeps writing manifest version 4, which means the same as a version 5 manifest with the default values.
