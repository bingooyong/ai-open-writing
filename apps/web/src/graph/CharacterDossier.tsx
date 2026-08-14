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
        <p className="dossier-kicker">人物档案</p>
        <h3 className="dossier-name muted-name">未选择人物</h3>
        <p className="muted">
          点选图中节点，查看身份、关系与证据。无证据时标注「{MISSING_EVIDENCE}」。
        </p>
      </>
    );
  }

  return (
    <>
      <p className="dossier-kicker">人物档案</p>
      <h3 className="dossier-name">{insight.name}</h3>
      <div className="stat-tiles">
        <div>
          <strong>{inspector.degree}</strong>
          <span>关系数</span>
        </div>
        <div>
          <strong>{inspector.appearanceChapters}</strong>
          <span>出现章节</span>
        </div>
        <div>
          <strong>{inspector.turningBeats}</strong>
          <span>关系转折</span>
        </div>
      </div>
      <p className="dossier-oneliner">{insight.oneLiner}</p>
      <p className="dossier-note">依据已落库的图谱与圣经快照，不另跑一层分析。</p>
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
