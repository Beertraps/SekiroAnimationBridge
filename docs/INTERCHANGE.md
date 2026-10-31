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
| Character export manifest | `blender_bridge.py export-character` | `character_export.py`, which writes a new Sekiro character | [`character_export.schema.json`](../standalone/schemas/character_export.schema.json) |
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
| Triangle | corner order kept (see below) |
| Bone rest matrix *M* | `C · M · C⁻¹` with `C = unitScale · B` |

Known spaces:

| Engine | `basis` | `unitScale` | Meaning |
| --- | --- | --- | --- |
| FromSoftware (Havok, FLVER) | `[[1,0,0],[0,0,1],[0,1,0]]` | 1 | Y up, left-handed: swap Y and Z, which reflects |
| RE Engine | `[[1,0,0],[0,0,-1],[0,1,0]]` | 1 | Y up, right-handed: +90° about X, no reflection |
| Unreal Engine 4 and 5 | `[[1,0,0],[0,-1,0],[0,0,1]]` | 0.01 | Z up, left-handed, centimetres: flip Y, which reflects |

A triangle keeps its corner order. Seen from the front, its corners run counter-clockwise in a right-handed source and clockwise in a left-handed one (`det(B) = −1`), as FLVER and Unreal meshes do. The mirror of a left-handed basis turns them counter-clockwise, which is how Blender winds a front face. A source that winds the other way reverses its triangles when it writes `faces`: id Tech is right-handed and winds clockwise, so the DOOM Eternal package swaps two corners of each triangle.

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

### Additive clips

An additive clip holds changes that the game puts on top of the pose below it, not a pose. Its motion JSON has an
`additive` object; a normal clip has none, so its JSON stays as before.

| Field | Type | Meaning |
| --- | --- | --- |
| `additive.blendHint` | 1 or 2 | Havok's `hkaAnimationBinding.blendHint`: 1 `ADDITIVE_DEPRECATED`, 2 `ADDITIVE`. Absent for a clip from another engine. |
| `additive.space` | `parent`, `child` or `separate` | how a change *D* goes on a base pose *B*: `parent` (blendHint 1) is *D* · *B*, `child` (blendHint 2) is *B* · *D*, `separate` (DOOM Eternal) composes each part on its own |
| `additive.base` | null or object | the normal clip that Blender shows the changes on: `clip`, `frameRate`, `trackBoneIndices[]`, `frames[f][t]` as in a motion JSON. Absent or null: the rest pose. |

`frames` then holds the changes. A channel the clip does not animate is no change: translation 0, rotation
identity, scale 1, not the rest value. In parent space, per bone in its parent's space:

    pose.translation = D.translation + D.rotation · B.translation
    pose.rotation    = D.rotation · B.rotation
    pose.scale       = D.scale · B.scale

So a change made from a pose *A* on *B* is `rotation = A.r · B.r⁻¹`, `translation = A.t − rotation · B.t`,
`scale = A.s / B.s`. `standalone/games/additive.py` has both directions. Sekiro uses blendHint 1 only; the child-space
formula is inferred from Havok's names.

In `separate` space the change's rotation does not turn the base's translation:

    pose.translation = B.translation + D.translation
    pose.rotation    = D.rotation · B.rotation
    pose.scale       = D.scale · B.scale

So a change made from *A* on *B* is `rotation = A.r · B.r⁻¹`, `translation = A.t − B.t`, `scale = A.s / B.s`. DOOM
Eternal's additive md6 clips are in this form ([games/doom_eternal.md](games/doom_eternal.md#additive-clips)).

The base clip repeats from its start when the additive clip runs longer, as Havok loops a clip: the base frame at
time *t* is `round(t · frameRate) mod (frameCount − 1)`. Bones that the base moves and the additive clip has no track
for show the base's pose. Export writes `additive` back; with `export --additive` a normal clip's scene gets
`{"blendHint": 1, "space": "parent"}`, and for `first-frame` also a `base` of that one frame. Havok has no
`separate` form, so export takes the base off in parent space and writes blendHint 1: on the same base, the
game shows the same pose.

## Character manifest

`character.json`: the models of a character, their materials and the paths of their arrays and textures.

| Field | Meaning |
| --- | --- |
| `version` | 4 or 5 |
| `game` | the game's ID |
| `models[]` | `name`, `source` (the file it came from), `data` (path of its `.npz`), `materials[]`, `stats`, `attachment` (a weapon's socket, or null), `role` (optional: `Body`, `Head`, `Hair`, `Weapon` and so on, the name of its objects in Blender) |
| `models[].attachment` | null for a part of the character. A game package's weapon has `{"kind": "joint", "bone": "R_WeaponHand"}`: its root bones hang below that bone of the rig, its bones' rest pose and its vertices are relative to the bone, and it moves with it. Its bone names must not be the character's, so a package names them after the weapon, such as `wp01_000_root`. FromSoftware weapons carry their dummy, matrix and bone instead. |
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
| image `packed` | what other data the image's channels hold, as `{channel: role}`: channel `R`, `G`, `B` or `A`, role `metalness`, `roughness`, `opacity` or `emissive`. RE Engine's ALBM albedo is `{"A": "metalness"}` and its NRMR normal map is `{"A": "roughness"}`. |
| `models[].materials[].metalness`, `roughness` | null or an image whose `channel` (`R` by default) holds that value, for sources that keep it in an image of its own |
| `models[].role` | the part's label in Blender, such as `Body`, `Head` or `Hair`; FromSoftware models are labelled by their file prefix |

All version 5 fields are optional except `version`; a reader treats a missing one as its default, so the FromSoftware characters stay version 4.

Blender's preview shows albedo, opacity, normal and emissive. When an image is `packed` or a material has `metalness` or `roughness`, the import stores every role in the material's `bridge_texture_roles` property, so a character export finds them without reading the node tree.

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
| `faces` | (m, 3) int32 | triangles, front faces wound as the source's handedness winds them (see Source space) |
| `face_materials` | (m,) int32 | index into the model's materials |
| `vertex_materials` | (n,) int32 | the material of the submesh each vertex belongs to |
| `bone_names` | (b,) str | the model's bones |
| `bone_parents` | (b,) int32 | parent index, −1 for a root |
| `bone_translations` | (b, 3) float32 | local rest translation |
| `bone_rotations` | (b, 3) float32 | local rest rotation as Euler XZY (manifest `boneRotation` `euler_xzy`) |
| `bone_quaternions` | (b, 4) float32 | local rest rotation as [x, y, z, w] (manifest `boneRotation` `quaternion`) |
| `bone_scales` | (b, 3) float32 | local rest scale |
| `material_names` | (k,) str | one per material |

## Character export manifest

`manifest.json`, written by `blender --background SCENE --python blender_bridge.py -- export-character --output-dir FOLDER`: one rig, the meshes that move with it, their materials and one action. `format` is `"sekiro-animation-bridge-character-export"` and `version` is 1. Everything is in Blender's space (`space` `blender`, `unit` `meter`, Z up, world coordinates); the game writer converts it to the game's space.

A visible mesh moves with the rig in one of three ways, which `meshes[].bound` names:

- `rig`: an Armature modifier binds it to the rig.
- `bone`: it moves with one bone as a whole. It is parented to that bone, or it hangs below an object that a Child Of or Copy Transforms constraint holds on the bone. All its vertices take that bone, with weight 1.
- `armature`: an Armature modifier binds it to another armature that moves with a bone of the rig as a whole, as the bridge's weapon rigs follow their sockets. That armature's bones come after the rig's in `bones[]`, below the bone, and its motion is sampled with theirs. A name the rig has already takes the armature's name before it, such as `WP_A_0300_Blade00`.

For `bone` and `armature`, the mesh and the bones are carried back from the scene's current frame to where they are when the bone rests. Visible meshes that move with the rig in none of these ways are listed in `leftOut[]`.

| Field | Meaning |
| --- | --- |
| `rig` | the armature object's name |
| `bones[]` | `name`, `parent` (−1 for a root; parents come first), `rest`: the bone's world rest matrix, 16 numbers row by row |
| `meshes[]` | `name`, `data` (path of the mesh's `.npz`), `bound` (`rig`, `bone` or `armature`), `bone` (for `bone` and `armature`: the rig's bone it moves with), `vertices`, `triangles`, `uvSets`, `unweightedVertices`, `weightsOutsideRig` |
| `leftOut[]` | `name` and `reason` of each visible mesh left out: bound to another armature, to a bind adapter that keeps a cutscene bind pose (an adapter whose bones rest within 1 mm of the rig's counts as the rig), to the rig object without a bone, or to nothing of the rig |
| `materials[]` | `name`, `roles`, `alpha`, `color`, `doubleSided`, `cutOut` |
| `materials[].roles` | `albedo`, `opacity`, `normal`, `metalness`, `roughness`, `emissive`, each `image` (the Blender image's name), `channel` (`RGB`, `R`, `G`, `B` or `A`), `path` (the image saved beside the manifest) and, for `normal`, `convention` |
| `materials[].alpha`, `color` | the shader's alpha and linear RGBA base color where no image drives them, else null. Alpha 0 marks an overlay the game cannot draw, such as eye wetness. |
| `warnings[]` | weights on groups that are not bones, vertices without a weight, and one line per reason in `leftOut[]` |
| `motion` | `action`, `frameStart`, `frameEnd`, `frameRate`, `frames`, `data` (path of `motion.npz`) |

A material's roles come from `bridge_texture_roles` when the import stored them, otherwise from the node tree: the image that feeds the Principled BSDF's Base Color, Alpha, Metallic, Roughness and Emission Color inputs, through Separate Color nodes, and the image behind a Normal Map node. A normal map counts as DirectX when a Math node feeds the green channel, as the import builds it.

Each mesh `.npz` holds the mesh's own data, triangulated and in world space. Modifiers are not applied; apply one in Blender first when the game should see its result.

| Array | Shape, type | Meaning |
| --- | --- | --- |
| `positions` | (n, 3) float32 | vertex positions |
| `loop_vertex` | (c,) int32 | the vertex of each corner |
| `normals` | (c, 3) float32 | corner normals |
| `tangents` | (c, 4) float32 | corner tangents; the fourth value is the bitangent sign |
| `uv_0`, `uv_1` | (c, 2) float32 | the first two UV maps, as Blender stores them (V up) |
| `triangles` | (m, 3) int32 | the corners of each triangle |
| `triangle_materials` | (m,) int32 | index into `materials[]` |
| `bone_indices`, `bone_weights` | (n, 4) | the four largest weights on bones of the rig, summing to 1 |

`motion.npz` holds `matrices`, shape (frames, bones, 4, 4) float32: each bone's world matrix at each frame from `frameStart` to `frameEnd`.

## Preview JSON

The skeleton preview's joint positions, gzipped by `clip_preview.preview`.

| Field | Meaning |
| --- | --- |
| `clip`, `skeleton` | names |
| `frameCount`, `frameRate`, `duration` | as in the motion JSON |
| `frameStep` | every `frameStep`th frame is included |
| `bones[]`, `parents[]` | the skeleton |
| `tracks` | number of animated bones |
| `positions[f]` | world positions, x, y, z per bone, in source space; an additive clip's changes on the rest pose |
| `detached[]` | bones far from the body, hidden by default |
| `root` | null or `[[x, y, z, yaw], …]` |
| `basis`, `unitScale` | optional source space; the FromSoftware space when absent |

## Versions

| Format | Version | Change |
| --- | --- | --- |
| Motion JSON | 1 | first version |
| Motion JSON | 2 | `source`, `basis`, `unitScale` |
| Motion JSON | 1 and 2 | `additive` (optional addition; decoder 0.7.0) |
| Character manifest | 4 | current FromSoftware manifest |
| Character manifest | 5 | `basis`, `unitScale`, `boneRotation`, normal-map convention |
| Character manifest | 5 | image `packed`, material `metalness` and `roughness` (optional additions) |
| Preview JSON | 3 | current; `basis` and `unitScale` are optional additions |
| Character export manifest | 1 | first version |

Readers accept every version in this table. Writers write the newest version they need: the FromSoftware path keeps writing manifest version 4, which means the same as a version 5 manifest with the default values.
