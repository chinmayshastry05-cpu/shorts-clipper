"""Tests: multi-anchor (tracked) render filtergraph construction."""

from shortsclipper.export import tracked_filtergraph


def test_tracked_filtergraph_two_runs():
    runs = [(0.0, 15.0, 0.25), (15.0, 30.0, 0.75)]
    graph, vout, aout = tracked_filtergraph(1920, 1080, runs, ass_name="cap.ass")
    parts = graph.split(";")
    vtrims = [p for p in parts if p.startswith("[0:v]trim")]
    atrims = [p for p in parts if p.startswith("[0:a]atrim")]
    assert len(vtrims) == 2 and len(atrims) == 2
    # Each run carries its own anchor: left-half crop then right-half crop.
    assert "trim=start=0.0:end=15.0" in vtrims[0] and "crop=608:1080:176:0" in vtrims[0]
    assert "trim=start=15.0:end=30.0" in vtrims[1] and "crop=608:1080:1136:0" in vtrims[1]
    assert "concat=n=2:v=1:a=0[vcat]" in graph
    assert "concat=n=2:v=0:a=1[acat]" in graph
    assert graph.endswith("ass=cap.ass[vout]")
    assert vout == "vout" and aout == "acat"


def test_tracked_filtergraph_no_audio_no_ass():
    graph, vout, aout = tracked_filtergraph(1920, 1080, [(0.0, 30.0, None)],
                                            ass_name=None, audio=False)
    assert "atrim" not in graph and "ass=" not in graph
    assert vout == "vcat" and aout is None


def test_tracked_filtergraph_center_run():
    # A run without a face crops dead-center (same as the v0.1 crop).
    graph, _, _ = tracked_filtergraph(1920, 1080, [(0.0, 10.0, None)])
    assert "crop=608:1080:656:0" in graph
