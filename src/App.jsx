import { useState, useEffect } from 'react'
import './App.css'
import { demoMode } from './demoData.js'
import { getIncident, getIncidentVessels, listIncidents } from './api/incidents.js'
import * as trafficAPI from './api/traffic.js'

function Icon({ children }) {
  return <span className="icon" aria-hidden="true">{children}</span>
}

function App() {
  const [activeNav, setActiveNav] = useState('Overview')
  const [playing, setPlaying] = useState(false)
  const [selectedVessel, setSelectedVessel] = useState(0)
  const [layers, setLayers] = useState({ sar: true, slick: true, vessels: true, currents: true })
  const [trafficMode, setTrafficMode] = useState('filtered')
  const [trafficStage, setTrafficStage] = useState(5)
  const [alertVisible, setAlertVisible] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [incident, setIncident] = useState(null)
  const [vessels, setVessels] = useState([])
  const [incidentsList, setIncidentsList] = useState([])
  const [trafficStages, setTrafficStages] = useState([])
  const [loading, setLoading] = useState(true)

  // Load data from API on component mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const [incidentData, vesselsData, trafficStagesData, allIncidents] = await Promise.all([
          getIncident('INC-240824-01'),
          getIncidentVessels('INC-240824-01'),
          trafficAPI.getTrafficStages(),
          listIncidents(),
        ])
        setIncident(incidentData)
        setVessels(vesselsData)
        setTrafficStages(trafficStagesData)
        setIncidentsList(allIncidents || [])
      } catch (error) {
        console.error('Failed to load data:', error)
        // Data loading will use fallback demo data in API layer
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [])

  // Show loading state if incident not yet loaded
  if (loading || !incident || vessels.length === 0) {
    return (
      <div className="app-shell">
        <header className="topbar">
          <div className="brand"><div className="brand-mark"><span /></div><div><strong>OCEAN<span>TRACE</span></strong><small>MARITIME INTELLIGENCE</small></div></div>
          <nav>{['Overview'].map((item) => <button key={item} className="active">{item}</button>)}</nav>
          <div className="top-actions"><span className="live"><i /> LIVE SYSTEM</span><button className="avatar">AR</button></div>
        </header>
        <main><section className="intro"><h1>Loading incident data...</h1></section></main>
      </div>
    )
  }

  const toggleLayer = (layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark"><span /></div><div><strong>OCEAN<span>TRACE</span></strong><small>MARITIME INTELLIGENCE</small></div></div>
        <nav>{['Overview', 'Incidents', 'Vessels', 'Data layers'].map((item) => <button key={item} className={activeNav === item ? 'active' : ''} onClick={() => setActiveNav(item)}>{item}</button>)}</nav>
        <div className="top-actions"><span className="live"><i /> LIVE SYSTEM</span><button className="avatar">AR</button></div>
      </header>

      <main>
        {activeNav === 'Overview' && (
          <>
            <section className="intro"><div><p className="eyebrow">OPERATIONS / NORTH INDIAN OCEAN</p><h1>Spill intelligence <em>at a glance.</em></h1></div><div className="scene-meta"><span className="status-dot" /> <div><b>{incident.scene}</b><small>Processed 08:42 UTC &nbsp; / &nbsp; Confidence {incident.slick.confidence}% &nbsp; / &nbsp; {demoMode ? 'DEMO MODE' : 'LIVE'}</small></div><button className="ghost-button" onClick={() => window.location.href = '/report'}><Icon>↗</Icon> Export report</button></div></section>

            <section className="stats"><div className="stat"><span>ACTIVE INCIDENTS</span><strong>{String(incidentsList.length || 1).padStart(2, '0')}</strong><small className="up"><i>{incidentsList.length || 1} verified</i></small></div><div className="stat"><span>DETECTED SLICK AREA</span><strong>{incident.slick.area.replace(' km²', '')} <small>km²</small></strong><small className="up">+3.2% <i>last 6 hours</i></small></div><div className="stat"><span>VESSELS IN ENVELOPE</span><strong>{String(vessels.length).padStart(2, '0')}</strong><small><i>{vessels.filter(v => v.score >= 50).length} high priority</i></small></div><div className="stat"><span>MODEL CONFIDENCE</span><strong>{incident.slick.confidence}<small>%</small></strong><small className="up">+0.8% <i>vs. last run</i></small></div></section>

            <section className="traffic-control panel"><div><span className="section-kicker">TRAFFIC FILTERING</span><strong>{trafficMode === 'filtered' ? 'Operational traffic' : 'Normal traffic'}</strong><small>{trafficMode === 'filtered' ? 'Showing attribution candidates' : 'Regional AIS filter funnel (historical baseline)'}</small></div><div className="traffic-stages">{trafficStages.map((stage, index) => <button key={stage.label} className={trafficStage === index ? 'selected' : ''} onClick={() => setTrafficStage(index)}><span>{stage.label}</span><b>{stage.count}</b></button>)}</div><div className="traffic-mode"><button className={trafficMode === 'normal' ? 'selected' : ''} onClick={() => setTrafficMode('normal')}>Normal Traffic</button><button className={trafficMode === 'filtered' ? 'selected' : ''} onClick={() => setTrafficMode('filtered')}>Operational</button></div></section>

            <section className="workspace-grid">
              <div className="map-panel panel"><div className="panel-heading"><div><span className="section-kicker">01 / DETECTION &amp; TRACKING</span><h2>Incident map</h2></div><div className="map-actions"><button className="icon-button">−</button><button className="icon-button">+</button><button className="icon-button">⌖</button></div></div>
                <div className={`map-canvas ${trafficMode === 'normal' ? 'normal-traffic' : ''}`}>{layers.sar && <div className="sar-overlay" />}<div className="map-label label-india">INDIA</div><div className="map-label label-sri">SRI LANKA</div><div className="map-label label-sea">ARABIAN SEA</div>{layers.slick && <><div className="slick slick-one" /><div className="slick slick-two" /></>}<div className="track track-one" /><div className="track track-two" />{layers.vessels && <><div className="vessel v-one">◆</div><div className="vessel v-two">◆</div><div className="vessel v-three">◆</div></>}{layers.currents && <><div className="current c-one">›››››</div><div className="current c-two">›››››</div></>}<div className="map-tooltip"><span className="pulse" /><div><b>{incident.id}</b><small>Oil slick detected · {incident.slick.area}</small></div><strong>WARNING</strong></div><div className="coordinates">{incident.coordinates}</div><div className="north">N<br /><span>↑</span></div></div>
                <div className="map-footer"><div className="layer-toggles"><label><input type="checkbox" checked={layers.sar} onChange={() => toggleLayer('sar')} /><span className="swatch sar" /> SAR imagery</label><label><input type="checkbox" checked={layers.slick} onChange={() => toggleLayer('slick')} /><span className="swatch slick-swatch" /> Slick overlay</label><label><input type="checkbox" checked={layers.vessels} onChange={() => toggleLayer('vessels')} /><span className="swatch vessel-swatch" /> Vessels</label><label><input type="checkbox" checked={layers.currents} onChange={() => toggleLayer('currents')} /><span className="swatch current-swatch" /> Currents</label></div><span className="map-source">© OpenSeaMap &nbsp; / &nbsp; Sentinel-1 GRD</span></div>
              </div>

              <aside className="side-column"><div className="panel signal-panel"><div className="panel-heading"><div><span className="section-kicker">02 / PRIORITY QUEUE</span><h2>Suspect vessels <span className="count">{String(vessels.length).padStart(2, '0')}</span></h2></div><button className="more">•••</button></div><div className="vessel-list">{vessels.map((vessel, index) => <button className={`vessel-row ${selectedVessel === index ? 'selected' : ''}`} key={vessel.mmsi} onClick={() => setSelectedVessel(index)}><span className={`rank ${vessel.color}`}>0{index + 1}</span><div className="vessel-info"><b>{vessel.name}</b><small>MMSI {vessel.mmsi} &nbsp;·&nbsp; {vessel.flag}</small><span className={`vessel-note ${vessel.color}`}>{vessel.reasons[0]}</span></div><span className={`score ${vessel.color}`}>{vessel.score}<small>/100</small></span></button>)}</div><button className="full-list" onClick={() => setDetailsOpen(true)}>View attribution details <span>→</span></button></div>{alertVisible && <div className="panel alert-panel"><span className="alert-icon">!</span><div><b>Dark vessel detected</b><p>Unidentified hull in SAR scene. AIS match pending.</p><small>2 minutes ago</small></div><button className="close-alert" onClick={() => setAlertVisible(false)}>×</button></div>}</aside>
            </section>

            <section className="incident-details panel"><div className="details-heading"><div><span className="section-kicker">INCIDENT CHARACTERIZATION</span><h2>{incident.id} <small>· {incident.impact.severity.toUpperCase()}</small></h2></div><button className="details-toggle" onClick={() => setDetailsOpen(!detailsOpen)}>{detailsOpen ? 'Collapse' : 'Open forensic details'} ↗</button></div><div className="detail-metrics"><div><small>SLICK AGE</small><b>{incident.slick.age}</b></div><div><small>PERIMETER / L × W</small><b>{incident.slick.perimeter} / {incident.slick.length} × {incident.slick.width}</b></div><div><small>ASPECT RATIO</small><b>{incident.slick.aspect}</b></div><div><small>EST. VOLUME</small><b>{incident.slick.volume}</b></div><div><small>GEOMETRY</small><b>{incident.slick.geometry}</b></div></div>{detailsOpen && <div className="attribution-detail"><div><b>Explainable attribution · {vessels[selectedVessel].name}</b><p>Overall score {vessels[selectedVessel].score}/100. Weighted formula: 30% proximity + 25% trajectory + 25% behavior + 20% AIS gap.</p><div className="breakdown">{Object.entries(vessels[selectedVessel].breakdown).map(([key, value]) => <span key={key}><i style={{ width: `${value}%` }} /><b>{key} <em>{value}</em></b></span>)}</div></div><ul>{vessels[selectedVessel].reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}</section>

            <section className="timeline panel"><div className="timeline-head"><div><span className="section-kicker">03 / DRIFT SIMULATION</span><h2>Hindcast &amp; forecast</h2></div><div className="timeline-meta"><span className="legend"><i className="hindcast" /> Hindcast</span><span className="legend"><i className="forecast" /> Forecast</span><b>UTC</b></div></div><div className="timeline-body"><button className="play" onClick={() => setPlaying(!playing)}>{playing ? 'Ⅱ' : '▶'}</button><div className="scrubber"><div className="scrub-line"><span className="scrub-progress" style={{ width: playing ? '68%' : '44%' }} /><i className="scrub-knob" style={{ left: playing ? '68%' : '44%' }} /></div><div className="dates"><span>22 AUG<br /><b>00:00</b></span><span>23 AUG<br /><b>00:00</b></span><span className="now">24 AUG<br /><b>08:42</b></span><span>25 AUG<br /><b>00:00</b></span><span>26 AUG<br /><b>00:00</b></span></div></div><button className="speed">1× <span>⌄</span></button></div></section>
          </>
        )}

        {activeNav === 'Incidents' && (
          <>
            <section className="intro">
              <div>
                <p className="eyebrow">OPERATIONS / INCIDENT MANAGEMENT</p>
                <h1>Active incidents <em>directory.</em></h1>
              </div>
              <div className="scene-meta">
                <span className="status-dot" />
                <div>
                  <b>{incident.id}</b>
                  <small>Severity: {incident.impact.severity.toUpperCase()} &nbsp; / &nbsp; Impact Coast: {incident.impact.coast}</small>
                </div>
                <button className="ghost-button" onClick={() => window.location.href = '/report'}><Icon>↗</Icon> Export report</button>
              </div>
            </section>

            <section className="stats">
              <div className="stat"><span>ACTIVE INCIDENTS</span><strong>{String(incidentsList.length || 1).padStart(2, '0')}</strong><small className="up"><i>{incidentsList.length || 1} verified</i></small></div>
              <div className="stat"><span>DETECTED SLICK AREA</span><strong>{incident.slick.area.replace(' km²', '')} <small>km²</small></strong><small className="up">+3.2% <i>last 6 hours</i></small></div>
              <div className="stat"><span>IMPACT RISK SCORE</span><strong>{incident.impact.score}<small>/100</small></strong><small><i>ETA {incident.impact.eta}</i></small></div>
              <div className="stat"><span>MODEL CONFIDENCE</span><strong>{incident.slick.confidence}<small>%</small></strong><small className="up">+0.8% <i>vs. last run</i></small></div>
            </section>

            <section className="incident-details panel" style={{ marginTop: 0 }}>
              <div className="details-heading">
                <div>
                  <span className="section-kicker">INCIDENT DOSSIER</span>
                  <h2>{incident.id} <small>· {incident.source} · {incident.coordinates}</small></h2>
                </div>
                <span className="live"><i /> VERIFIED SPILL</span>
              </div>
              <div className="detail-metrics">
                <div><small>DETECTION TIME</small><b>{incident.detected}</b></div>
                <div><small>SCENE IDENTIFIER</small><b>{incident.scene}</b></div>
                <div><small>COORDINATES</small><b>{incident.coordinates}</b></div>
                <div><small>IMPACT TARGET</small><b>{incident.impact.coast}</b></div>
                <div><small>PROJECTED ETA</small><b>{incident.impact.eta}</b></div>
              </div>
              <div className="detail-metrics" style={{ borderTop: '1px solid var(--line)' }}>
                <div><small>SLICK AGE</small><b>{incident.slick.age}</b></div>
                <div><small>EST. VOLUME</small><b>{incident.slick.volume}</b></div>
                <div><small>PERIMETER</small><b>{incident.slick.perimeter}</b></div>
                <div><small>DIMENSIONS (L × W)</small><b>{incident.slick.length} × {incident.slick.width}</b></div>
                <div><small>ASPECT RATIO</small><b>{incident.slick.aspect}</b></div>
              </div>
              <div className="attribution-detail">
                <div>
                  <b>Forecast &amp; Trajectory Summary</b>
                  <p>{incident.forecast || `Oil slick trajectory modeled under prevailing coastal current regimes heading toward ${incident.impact.coast}. Simulation envelope indicates potential shoreline impact in approximately ${incident.impact.eta}.`}</p>
                </div>
                <div>
                  <b>Detection Parameters</b>
                  <ul style={{ marginTop: 8 }}>
                    <li>Satellite Sensor: Sentinel-1 C-SAR IW mode (Interferometric Wide)</li>
                    <li>Slick Morphology: {incident.slick.geometry} with {incident.slick.confidence}% confidence</li>
                    <li>Environmental Wind: {incident.environment?.wind || '14.2 knots @ 245° (WSW)'}</li>
                    <li>Ocean Surface Current: {incident.environment?.current || '1.1 knots @ 085° (ENE)'}</li>
                  </ul>
                </div>
              </div>
            </section>
          </>
        )}

        {activeNav === 'Vessels' && (
          <>
            <section className="intro">
              <div>
                <p className="eyebrow">INTELLIGENCE / ATTRIBUTION MATRIX</p>
                <h1>Vessel attribution <em>registry.</em></h1>
              </div>
              <div className="scene-meta">
                <span className="status-dot" />
                <div>
                  <b>{vessels.length} CANDIDATES EVALUATED</b>
                  <small>Selected: {vessels[selectedVessel]?.name} &nbsp; / &nbsp; Score {vessels[selectedVessel]?.score}/100</small>
                </div>
                <button className="ghost-button" onClick={() => window.location.href = '/report'}><Icon>↗</Icon> Export report</button>
              </div>
            </section>

            <section className="stats">
              <div className="stat"><span>VESSELS IN ENVELOPE</span><strong>{String(vessels.length).padStart(2, '0')}</strong><small><i>{vessels.length} suspect candidates</i></small></div>
              <div className="stat"><span>PRIMARY SUSPECT</span><strong>{vessels[0]?.name}</strong><small className="up">Score: {vessels[0]?.score}/100</small></div>
              <div className="stat"><span>DARK AIS TARGETS</span><strong>{String(vessels.filter(v => v.dark === 'Confirmed').length).padStart(2, '0')}</strong><small><i>Uncorrelated hull in scene</i></small></div>
              <div className="stat"><span>ATTRIBUTION MODEL</span><strong>P-LDHE</strong><small className="up">Physics + ML Correlation</small></div>
            </section>

            <div className="workspace-grid">
              <div className="panel signal-panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">CANDIDATE RANKING</span>
                    <h2>Suspect vessels queue <span className="count">0{vessels.length}</span></h2>
                  </div>
                </div>
                <div className="vessel-list">
                  {vessels.map((vessel, index) => (
                    <button
                      className={`vessel-row ${selectedVessel === index ? 'selected' : ''}`}
                      key={vessel.mmsi}
                      onClick={() => setSelectedVessel(index)}
                    >
                      <span className={`rank ${vessel.color}`}>0{index + 1}</span>
                      <div className="vessel-info">
                        <b>{vessel.name}</b>
                        <small>MMSI {vessel.mmsi} &nbsp;·&nbsp; {vessel.flag} &nbsp;·&nbsp; Route: {vessel.origin} → {vessel.destination}</small>
                        <span className={`vessel-note ${vessel.color}`}>{vessel.reasons[0]}</span>
                      </div>
                      <span className={`score ${vessel.color}`}>{vessel.score}<small>/100</small></span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">FORENSIC BREAKDOWN</span>
                    <h2>{vessels[selectedVessel]?.name}</h2>
                  </div>
                  <span className="live"><i /> MMSI {vessels[selectedVessel]?.mmsi}</span>
                </div>
                <div style={{ padding: '16px 22px' }}>
                  <div className="detail-metrics" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 16 }}>
                    <div><small>FLAG STATE</small><b>{vessels[selectedVessel]?.flag}</b></div>
                    <div><small>DARK STATUS</small><b style={{ color: vessels[selectedVessel]?.dark === 'Confirmed' ? 'var(--red)' : 'var(--text)' }}>{vessels[selectedVessel]?.dark}</b></div>
                    <div><small>ATTRIBUTION SCORE</small><b>{vessels[selectedVessel]?.score}/100</b></div>
                  </div>
                  <div className="detail-metrics" style={{ gridTemplateColumns: 'repeat(2, 1fr)', borderTop: '1px solid var(--line)', marginBottom: 16 }}>
                    <div><small>ORIGIN PORT</small><b>{vessels[selectedVessel]?.origin}</b></div>
                    <div><small>DESTINATION</small><b>{vessels[selectedVessel]?.destination}</b></div>
                  </div>
                  <div style={{ borderTop: '1px solid var(--line)', paddingTop: 16 }}>
                    <small style={{ color: 'var(--muted)', fontSize: 9, letterSpacing: 1 }}>EXPLAINABLE WEIGHTED SCORES</small>
                    <div className="breakdown" style={{ marginTop: 10 }}>
                      {Object.entries(vessels[selectedVessel]?.breakdown || {}).map(([key, value]) => (
                        <span key={key}>
                          <i style={{ width: `${value}%` }} />
                          <b>{key} <em>{value}</em></b>
                        </span>
                      ))}
                    </div>
                  </div>
                  <div style={{ borderTop: '1px solid var(--line)', marginTop: 18, paddingTop: 14 }}>
                    <small style={{ color: 'var(--muted)', fontSize: 9, letterSpacing: 1 }}>EVIDENCE &amp; REASON CODES</small>
                    <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none' }}>
                      {vessels[selectedVessel]?.reasons?.map((reason) => (
                        <li key={reason} style={{ color: '#a4b8b3', fontSize: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
                          <span style={{ color: 'var(--lime)', marginRight: 8 }}>✓</span>{reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}

        {activeNav === 'Data layers' && (
          <>
            <section className="intro">
              <div>
                <p className="eyebrow">TELEMETRY / SENSOR INTEGRATION</p>
                <h1>Data layers &amp; <em>environmental feeds.</em></h1>
              </div>
              <div className="scene-meta">
                <span className="status-dot" />
                <div>
                  <b>SENTINEL-1 IW GRD</b>
                  <small>Acquisition: {incident.detected} &nbsp; / &nbsp; Resolution: 10m/px</small>
                </div>
                <button className="ghost-button" onClick={() => window.location.href = '/report'}><Icon>↗</Icon> Export report</button>
              </div>
            </section>

            <section className="traffic-control panel">
              <div>
                <span className="section-kicker">TRAFFIC FILTERING</span>
                <strong>{trafficMode === 'filtered' ? 'Operational traffic' : 'Normal traffic'}</strong>
                <small>{trafficMode === 'filtered' ? 'Showing attribution candidates' : 'Regional AIS filter funnel (historical baseline)'}</small>
              </div>
              <div className="traffic-stages">
                {trafficStages.map((stage, index) => (
                  <button key={stage.label} className={trafficStage === index ? 'selected' : ''} onClick={() => setTrafficStage(index)}>
                    <span>{stage.label}</span>
                    <b>{stage.count}</b>
                  </button>
                ))}
              </div>
              <div className="traffic-mode">
                <button className={trafficMode === 'normal' ? 'selected' : ''} onClick={() => setTrafficMode('normal')}>Normal Traffic</button>
                <button className={trafficMode === 'filtered' ? 'selected' : ''} onClick={() => setTrafficMode('filtered')}>Operational</button>
              </div>
            </section>

            <div className="workspace-grid">
              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">ACTIVE DATA FEEDS</span>
                    <h2>Sensor and telemetry layers</h2>
                  </div>
                  <span className="map-source">© OpenSeaMap / Copernicus / NOAA GFS</span>
                </div>
                <div style={{ padding: '20px 22px' }}>
                  <div className="layer-toggles" style={{ flexDirection: 'column', gap: 16 }}>
                    <label style={{ fontSize: 12, cursor: 'pointer' }}>
                      <input type="checkbox" checked={layers.sar} onChange={() => toggleLayer('sar')} />
                      <span className="swatch sar" style={{ width: 12, height: 12 }} />
                      <b>Sentinel-1 SAR Imagery (IW GRD)</b>
                      <small style={{ color: 'var(--muted)', marginLeft: 8 }}>Synthetic Aperture Radar amplitude backscatter</small>
                    </label>
                    <label style={{ fontSize: 12, cursor: 'pointer' }}>
                      <input type="checkbox" checked={layers.slick} onChange={() => toggleLayer('slick')} />
                      <span className="swatch slick-swatch" style={{ width: 12, height: 12 }} />
                      <b>Model 1 Spill Segmentation Overlay</b>
                      <small style={{ color: 'var(--muted)', marginLeft: 8 }}>Deep neural polygon classification mask (Confidence {incident.slick.confidence}%)</small>
                    </label>
                    <label style={{ fontSize: 12, cursor: 'pointer' }}>
                      <input type="checkbox" checked={layers.vessels} onChange={() => toggleLayer('vessels')} />
                      <span className="swatch vessel-swatch" style={{ width: 12, height: 12 }} />
                      <b>AIS Vessel Positions &amp; Corridors</b>
                      <small style={{ color: 'var(--muted)', marginLeft: 8 }}>Live AISStream + historical corridor interpolation</small>
                    </label>
                    <label style={{ fontSize: 12, cursor: 'pointer' }}>
                      <input type="checkbox" checked={layers.currents} onChange={() => toggleLayer('currents')} />
                      <span className="swatch current-swatch" style={{ width: 12, height: 12 }} />
                      <b>Ocean Surface Currents &amp; Wind Vector Fields</b>
                      <small style={{ color: 'var(--muted)', marginLeft: 8 }}>Hydrodynamic hindcast/forecast vector field</small>
                    </label>
                  </div>
                </div>
                <div className="detail-metrics" style={{ borderTop: '1px solid var(--line)' }}>
                  <div><small>SAR SCENE</small><b>{incident.scene}</b></div>
                  <div><small>PASS TYPE</small><b>Descending / Interferometric</b></div>
                  <div><small>INCIDENCE ANGLE</small><b>34.2° – 41.8°</b></div>
                  <div><small>GRID RESOLUTION</small><b>10m × 10m pixel size</b></div>
                  <div><small>CALIBRATION</small><b>Radiometric Gamma-0</b></div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">ENVIRONMENTAL CONDITIONS</span>
                    <h2>Metocean parameters</h2>
                  </div>
                </div>
                <div style={{ padding: '20px 22px' }}>
                  <div className="detail-metrics" style={{ gridTemplateColumns: '1fr 1fr', gap: 10, border: 'none' }}>
                    <div style={{ borderRight: '1px solid var(--line)' }}>
                      <small>SURFACE WIND SPEED</small>
                      <strong style={{ fontSize: 20, color: '#ecf7ed', display: 'block', margin: '8px 0 4px' }}>14.2 <small style={{ fontSize: 11, color: 'var(--muted)' }}>kts</small></strong>
                      <small style={{ color: 'var(--muted)' }}>Direction: 245° (WSW)</small>
                    </div>
                    <div>
                      <small>SURFACE CURRENT</small>
                      <strong style={{ fontSize: 20, color: '#ecf7ed', display: 'block', margin: '8px 0 4px' }}>1.1 <small style={{ fontSize: 11, color: 'var(--muted)' }}>kts</small></strong>
                      <small style={{ color: 'var(--muted)' }}>Direction: 085° (ENE)</small>
                    </div>
                  </div>
                  <div className="detail-metrics" style={{ gridTemplateColumns: '1fr 1fr', gap: 10, borderTop: '1px solid var(--line)', marginTop: 14, paddingTop: 14 }}>
                    <div style={{ borderRight: '1px solid var(--line)' }}>
                      <small>SIGNIFICANT WAVE HT</small>
                      <strong style={{ fontSize: 20, color: '#ecf7ed', display: 'block', margin: '8px 0 4px' }}>1.4 <small style={{ fontSize: 11, color: 'var(--muted)' }}>m</small></strong>
                      <small style={{ color: 'var(--muted)' }}>Period: 6.8 seconds</small>
                    </div>
                    <div>
                      <small>SEA SURFACE TEMP</small>
                      <strong style={{ fontSize: 20, color: '#ecf7ed', display: 'block', margin: '8px 0 4px' }}>28.6 <small style={{ fontSize: 11, color: 'var(--muted)' }}>°C</small></strong>
                      <small style={{ color: 'var(--muted)' }}>Thermal Stability: High</small>
                    </div>
                  </div>
                  <div style={{ borderTop: '1px solid var(--line)', marginTop: 16, paddingTop: 12 }}>
                    <small style={{ color: 'var(--muted)', fontSize: 9, letterSpacing: 1 }}>PHYSICS MODEL INGESTION</small>
                    <p style={{ color: '#779392', fontSize: 10, lineHeight: 1.5, margin: '6px 0 0' }}>
                      Model 2 uses P-LDHE (Lagrangian Particle Tracking) driven by these meteorological and oceanographic boundary conditions over the 48h search corridor.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </main><footer><span>OCEANTRACE OPS v1.8.2</span><span>ALL SYSTEMS NOMINAL <i /></span><span>LAST SYNC 08:44:12 UTC</span></footer>
    </div>
  )
}

export default App
