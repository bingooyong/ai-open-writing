import {
  MISSING_EVIDENCE,
  labeledEvidence,
  type CharacterInsight,
  type InspectorView,
} from "./mapGraphDto";

type Props = {
  inspector: InspectorView | null;
  insight: CharacterInsight | null;
};

export function CharacterDossier({ inspector, insight }: Props) {
  if (!inspector || !insight) {
    return (
      <>
        <h2>人物</h2>
        <p className="muted">点选图中节点查看关系与证据。无证据时标注「{MISSING_EVIDENCE}」。</p>
      </>
    );
  }

  return (
    <>
      <h2>人物</h2>
      <h3 className="dossier-name">{insight.name}</h3>
      <p className="dossier-oneliner">{insight.oneLiner}</p>
      <p className="dossier-meta">
        关系 {inspector.degree} · 章节 {inspector.appearanceChapters} · 转折 {inspector.turningBeats}
      </p>
      <h2>直接关系</h2>
      {inspector.edges.length === 0 ? (
        <p className="muted">当前范围内没有连到此人的边。</p>
      ) : (
        <ul className="tracks">
          {inspector.edges.map((edge) => (
            <li key={`${edge.counterpartId}-${edge.source_chapter}-${edge.label}`}>
              <div>
                {insight.name} → {edge.counterpartLabel}
              </div>
              <div className="muted">
                {edge.label}
                {edge.state && edge.state !== edge.label ? ` · ${edge.state}` : ""}
                {edge.provisional ? " · 暂定" : ""} · {edge.source_chapter}
              </div>
              <div>{edge.evidence}</div>
            </li>
          ))}
        </ul>
      )}
      <h2>关系轨迹</h2>
      {inspector.tracks.length === 0 ? (
        <p className="muted">尚无关系转折记录。</p>
      ) : (
        <ul className="tracks">
          {inspector.tracks.map((track) => (
            <li key={track.parties.join("-")}>
              {track.parties.join(" · ")}
              {track.beats.map((beat) => (
                <div key={`${beat.chapter_key}-${beat.from_state}-${beat.to_state}`} className="muted">
                  {beat.chapter_key}: {beat.from_state} → {beat.to_state}
                  <br />
                  {labeledEvidence(beat.evidence)}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
