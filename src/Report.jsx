import { useState, useEffect } from 'react'
import './Report.css'
import { demoMode } from './demoData.js'
import * as reportsAPI from './api/reports.js'
import * as incidentsAPI from './api/incidents.js'

function downloadGeoJson(incidentId) {
  reportsAPI.getReportGeoJSON(`RPT-${incidentId}`).then(geoJson => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(geoJson, null, 2)], { type: 'application/geo+json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `${incidentId}.geojson`
    link.click()
    URL.revokeObjectURL(url)
  })
}

function Report() {
  const [status, setStatus] = useState('READY FOR REVIEW')
  const [report, setReport] = useState(null)
  const [recommendations, setRecommendations] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadReport = async () => {
      try {
        const reportData = await reportsAPI.getReport('RPT-INC-240824-01')
        const recommendationsData = await incidentsAPI.getRecommendations('INC-240824-01')
        setReport(reportData)
        setRecommendations(recommendationsData)
      } catch (error) {
        console.error('Failed to load report:', error)
      } finally {
        setLoading(false)
      }
    }

    loadReport()
  }, [])

  if (loading || !report) {
    return (
      <div className="report-shell">
        <header className="report-topbar"><a className="report-brand" href="/"><span className="report-mark">✦</span><span><b>AQUA<span>VIGIL</span></b><small>SATELLITE INTELLIGENCE FOR OCEAN PROTECTION</small></span></a><div className="report-actions"><button className="report-outline" onClick={() => window.location.href = '/'}>← Dashboard</button></div></header>
        <main className="report-main"><p>Loading report data...</p></main>
      </div>
    )
  }

  const incident = report.incident
  const vessels = report.vessels
  const evidenceChain = report.evidence

  return (
    <div className="report-shell">
      <header className="report-topbar"><a className="report-brand" href="/"><span className="report-mark">✦</span><span><b>AQUA<span>VIGIL</span></b><small>SATELLITE INTELLIGENCE FOR OCEAN PROTECTION</small></span></a><div className="report-actions"><span className="report-status"><i /> {demoMode ? 'DEMO · ' : ''}{status}</span><button className="report-outline" onClick={() => window.location.href = '/'}>← Dashboard</button><button className="report-primary" onClick={() => { setStatus('PRINT DIALOG OPEN'); window.print() }}>⇩ Export PDF</button></div></header>
      <main className="report-main">
        <div className="report-title"><div><p className="report-kicker">FORENSIC INCIDENT REPORT / v1.0</p><h1>Oil spill intelligence brief</h1><p className="report-subtitle">A decision-ready summary generated from multi-modal satellite, AIS, and oceanographic analysis.</p></div><div className="report-stamp"><span>CONFIDENTIAL</span><b>{incident.id}</b><small>Generated 24 AUG 2026</small></div></div>

        <section className="report-grid report-overview"><div className="report-card incident-card"><div className="card-head"><span>01 / INCIDENT OVERVIEW</span><strong className="high-badge">HIGH RISK</strong></div><div className="incident-content"><div className="mini-map"><span className="map-cross">+</span><span className="map-pin">◆</span><small>ARABIAN SEA</small><b>14°32'N<br />68°18'E</b></div><div className="incident-facts"><div><small>DETECTED</small><b>{incident.detected}</b></div><div><small>LOCATION</small><b>{incident.coordinates}</b></div><div><small>SATELLITE SCENE</small><b>{incident.scene}</b></div></div></div></div><div className="report-card risk-card"><div className="card-head"><span>ENVIRONMENTAL RISK</span><span className="risk-label">ELEVATED</span></div><div className="risk-score"><strong>78</strong><span>/ 100</span><div className="risk-meter"><i /></div></div><p>Projected drift intersects a protected marine zone within 36 hours.</p><div className="impact-tags"><span>Marine habitat</span><span>Coastal fisheries</span><span>Protected zone</span></div></div></section>

        <section className="report-card metrics-card"><div className="card-head"><span>02 / DETECTION METRICS</span><span className="verified">● MULTI-MODAL VERIFIED</span></div><div className="metric-row"><div><small>SLICK AREA</small><strong>{incident.slick.area}</strong><span>+3.2% / 6 hours</span></div><div><small>MODEL CONFIDENCE</small><strong>{incident.slick.confidence}%</strong><span>Segmentation ensemble</span></div><div><small>EST. VOLUME</small><strong>{incident.slick.volume.replace(' m³', '')} <em>m³</em></strong><span>Medium viscosity</span></div><div><small>IMPACT WINDOW</small><strong>{incident.impact.eta.replace(' hours', '')} <em>hours</em></strong><span>Forecast horizon</span></div></div></section>

        <section className="report-card vessel-card"><div className="card-head"><div><span>03 / SOURCE VESSEL ANALYSIS</span><h2>Ranked candidates</h2></div><small>SPATIAL ENVELOPE · 25 AUG 00:00 UTC</small></div><div className="table-wrap"><table><thead><tr><th>RANK</th><th>VESSEL</th><th>MMSI / FLAG</th><th>ANOMALY</th><th>AIS STATUS</th><th>CONFIDENCE</th></tr></thead><tbody>{vessels.map((vessel, index) => <tr key={vessel.mmsi}><td><span className={`table-rank rank-${index}`}>0{index + 1}</span></td><td><b>{vessel.name}</b><small>{vessel.reasons[0]}</small></td><td>{vessel.mmsi}<small>{vessel.flag}</small></td><td><div className="table-score"><span style={{ width: `${vessel.score}%` }} /> </div></td><td><span className={vessel.dark === 'Confirmed' ? 'dark-flag' : 'clear-flag'}>{vessel.dark}</span></td><td><strong className={index === 0 ? 'danger-text' : ''}>{vessel.score}<small>/100</small></strong></td></tr>)}</tbody></table></div></section>

        <section className="report-grid bottom-grid"><div className="report-card conditions-card"><div className="card-head"><span>04 / HYDRODYNAMIC CONDITIONS</span><span className="data-source">CMEMS · ERA5</span></div><div className="condition-row"><div><small>SURFACE WIND</small><strong>18 <em>kn</em></strong><span>WSW · 247°</span></div><div><small>OCEAN CURRENT</small><strong>1.4 <em>kn</em></strong><span>ENE · 065°</span></div><div><small>WAVE HEIGHT</small><strong>1.8 <em>m</em></strong><span>Moderate sea</span></div></div></div><div className="report-card forecast-card"><div className="card-head"><span>05 / TRAJECTORY FORECAST</span><span className="forecast-live">● LIVE MODEL</span></div><div className="forecast-route"><div className="route-line"><i /><i /><i /><i /></div><div><b>ORIGIN</b><span>24 AUG · 08:42</span></div><div><b>+12 HOURS</b><span>25 AUG · 20:42</span></div><div><b>+36 HOURS</b><span>26 AUG · 20:42</span></div></div><p>Drift vector trending ENE. Coastal impact probability: <strong>moderate</strong>.</p></div></section>
        <section className="report-grid report-extra"><div className="report-card recommendation-card"><div className="card-head"><span>06 / RESPONSE DECISION SUPPORT</span><span className="data-source">NOT AUTHORITATIVE</span></div><p>Recommended next actions based on current model outputs:</p><ul>{recommendations.map((recommendation) => <li key={recommendation}>{recommendation}</li>)}</ul></div><div className="report-card evidence-card"><div className="card-head"><span>07 / EVIDENCE CHAIN</span><span className="verified">● VERIFIED</span></div><div className="chain">{evidenceChain.map(([label, time, hash], index) => <div key={label}><i className={index === evidenceChain.length - 1 ? 'last' : ''} /><b>{label}</b><small>{time} · SHA-256 {hash}</small></div>)}</div></div></section><div className="report-footer-note"><span>Prepared by AQUAVIGIL ANALYTICS ENGINE · {demoMode ? 'DETERMINISTIC DEMO MODE' : 'LIVE'}</span><span>Data sources: Sentinel-1 GRD · AIS · HYCOM · ERA5 · CMEMS</span><button onClick={() => downloadGeoJson(incident.id)}>Export GeoJSON ↗</button></div>
      </main>
    </div>
  )
}

export default Report
