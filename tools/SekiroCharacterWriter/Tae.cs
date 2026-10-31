#nullable enable
using System.Text.Json.Nodes;
using SoulsAssetPipeline.Animation;

// Gives an animation ID an entry of its own in a TAE, so the game plays the HKX of that ID with the events of a source
// entry. The source may sit in another TAE file, such as another category of the player's TAE.
//  - No entry: a copy of the source's events, playing its own HKX.
//  - An entry that plays its own HKX: kept as it is.
//  - An entry that borrows another ID's HKX: it keeps its events and plays its own HKX.
//  - An entry that imports another entry: it gets the events of the entry it imported and plays its own HKX.
// The written TAE is read back: the new entry has the expected events, and every other entry is unchanged.
static class TaeWriter
{
    public static object Run(JsonObject job)
    {
        string targetPath = Json.Text(job, "target");
        string sourcePath = Json.OptionalText(job, "source") ?? targetPath;
        long id = job["id"]!.GetValue<long>();
        long sourceId = job["sourceId"]!.GetValue<long>();
        string output = Json.Text(job, "output");

        byte[] original = File.ReadAllBytes(targetPath);
        var tae = TAE.Read(original);
        var source = Path.GetFullPath(sourcePath) == Path.GetFullPath(targetPath) ? tae : TAE.Read(File.ReadAllBytes(sourcePath));
        if (tae.Format != TAE.TAEFormat.SDT)
            throw new InvalidDataException($"The TAE is {tae.Format}, not Sekiro's format.");
        // Rewriting the TAE without a change shows how close SoulsFormats' layout is to the game's.
        bool unchangedIdentical = TAE.Read(original).Write().AsSpan().SequenceEqual(original);

        var existing = tae.Animations.FirstOrDefault(a => a.ID == id);
        string kind;
        TAE.Animation? events;
        long resolved = sourceId;
        if (existing == null)
        {
            kind = "added";
            events = Resolve(source, sourceId, ref resolved);
        }
        else if (existing.Header is TAE.Animation.AnimFileHeader.ImportOtherAnim import)
        {
            kind = "imported";
            resolved = import.ImportFromAnimID;
            events = Resolve(tae, resolved, ref resolved);
        }
        else if (existing.Header is TAE.Animation.AnimFileHeader.Standard { ImportsHKX: true } borrowing &&
                 borrowing.ImportHKXSourceAnimID >= 0)
        {
            kind = "borrowed";
            resolved = borrowing.ImportHKXSourceAnimID;
            events = existing;
        }
        else
        {
            kind = "own";
            events = null;
        }

        var before = tae.Animations.Where(a => a.ID != id).ToDictionary(a => a.ID, Describe);
        object? entry = null;
        if (events != null)
        {
            var header = events.Header is TAE.Animation.AnimFileHeader.Standard standard
                ? (TAE.Animation.AnimFileHeader.Standard)standard.GetClone()
                : new TAE.Animation.AnimFileHeader.Standard { AnimFileName = events.Header?.AnimFileName ?? "" };
            header.IsNullHeader = false;
            header.ImportsHKX = false;
            header.ImportHKXSourceAnimID = -1;
            var copy = new TAE.Animation(id, header)
            {
                ActionTracks = events.ActionTracks.Select(t => t.GetClone()).ToList(),
                Actions = events.Actions.Select(a => new TAE.Action(a.StartTime, a.EndTime, a.Type, a.Unk04,
                    (byte[])a.ParameterBytes.Clone()) { TrackIndex = a.TrackIndex }).ToList(),
            };
            if (existing != null)
                tae.Animations[tae.Animations.IndexOf(existing)] = copy;
            else
            {
                int place = tae.Animations.FindIndex(a => a.ID > id);
                tae.Animations.Insert(place < 0 ? tae.Animations.Count : place, copy);
            }
            byte[] written = tae.Write();
            var check = TAE.Read(written);
            var found = check.Animations.Where(a => a.ID == id).ToList();
            if (found.Count != 1)
                throw new InvalidDataException($"The rewritten TAE has {found.Count} entries for {id}.");
            if (found[0].Header is not TAE.Animation.AnimFileHeader.Standard { ImportsHKX: false })
                throw new InvalidDataException($"The rewritten entry {id} does not play its own HKX.");
            if (Events(found[0]) != Events(events))
                throw new InvalidDataException($"The rewritten entry {id} does not have the events of {resolved}.");
            var after = check.Animations.Where(a => a.ID != id).ToDictionary(a => a.ID, Describe);
            if (after.Count != before.Count || after.Any(pair => !before.TryGetValue(pair.Key, out var text) || text != pair.Value))
                throw new InvalidDataException("Another entry of the rewritten TAE differs from the original.");
            Json.WriteFile(output, written);
            entry = new { id, actions = found[0].Actions.Count, tracks = found[0].ActionTracks.Count };
        }
        return new
        {
            kind,
            changed = events != null,
            id,
            sourceId,
            eventsFrom = events != null ? resolved : id,
            entry,
            animations = tae.Animations.Count,
            unchangedIdentical,
        };
    }

    // The entry whose events an ID plays, following entries that import another entry.
    static TAE.Animation Resolve(TAE tae, long id, ref long resolved)
    {
        var seen = new HashSet<long>();
        while (true)
        {
            var anim = tae.Animations.FirstOrDefault(a => a.ID == id)
                ?? throw new InvalidDataException($"The TAE has no entry {id} to copy the events of.");
            if (anim.Header is not TAE.Animation.AnimFileHeader.ImportOtherAnim import)
            {
                resolved = id;
                return anim;
            }
            if (!seen.Add(id))
                throw new InvalidDataException($"The TAE entries that {id} imports form a loop.");
            id = import.ImportFromAnimID;
        }
    }

    // Header, tracks and events of an entry as text, for the readback.
    static string Describe(TAE.Animation anim)
    {
        string header = anim.Header switch
        {
            TAE.Animation.AnimFileHeader.Standard s => $"S{s.IsLoopByDefault}{s.ImportsHKX}{s.AllowDelayLoad}{s.ImportHKXSourceAnimID}",
            TAE.Animation.AnimFileHeader.ImportOtherAnim o => $"O{o.ImportFromAnimID}{o.Unknown}",
            _ => "-",
        };
        return header + "|" + Events(anim);
    }

    static string Events(TAE.Animation anim) =>
        string.Join(";", anim.ActionTracks.Select(t => $"{t.TrackType}:{(long)t.TrackData.DataType}")) + "|" +
        string.Join(";", anim.Actions.Select(a => $"{a.StartTime:R},{a.EndTime:R},{a.Type},{a.Unk04},{a.TrackIndex}," +
                                                   Convert.ToHexString(a.ParameterBytes)));
}
