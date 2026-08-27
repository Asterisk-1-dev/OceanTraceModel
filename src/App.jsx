import { useState } from 'react'
import './App.css'

const vessels = [
  { name: 'SEA ORCHID', mmsi: '477981200', flag: 'SG', score: 92, meta: '18 min dark period', color: 'red' },
  { name: 'PACIFIC MERIDIAN', mmsi: '636019874', flag: 'LR', score: 76, meta: 'Course deviation', color: 'amber' },
  { name: 'NORDIC STAR', mmsi: '311000452', flag: 'BS', score: 54, meta: '3.2 nm from slick', color: 'yellow' },
]

function Icon({ children }) {
  return <span className="icon" aria-hidden="true">{children}</span>
}

function App() {
  const [activeNav, setActiveNav] = useState('Overview')
  const [playing, setPlaying] = useState(false)
  const [selectedVessel, setSelectedVessel] = useState(0)
  const [layers, setLayers] = useState({ sar: true, slick: true, vessels: true, currents: true })

  const toggleLayer = (layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark"><span /></div><div><strong>OCEAN<span>TRACE</span></strong><small>MARITIME INTELLIGENCE</small></div></div>
        <nav>{['Overview', 'Incidents', 'Vessels', 'Data layers'].map((item) => <button key={item} className={activeNav === item ? 'active' : ''} onClick={() => setActiveNav(item)}>{item}</button>)}</nav>
        <div className="top-actions"><span className="live"><i /> LIVE SYSTEM</span><button className="avatar">AR</button></div>
      </header>

      <main>
        <section className="intro"><div><p className="eyebrow">OPERATIONS / NORTH INDIAN OCEAN</p><h1>Spill intelligence <em>at a glance.</em></h1></div><div className="scene-meta"><span className="status-dot" /> <div><b>SCENE S1A_20260824_0417</b><small>Processed 08:42 UTC &nbsp; / &nbsp; Confidence 96.4%</small></div><button className="ghost-button"><Icon>↗</Icon> Export report</button></div></section>

        <section className="stats"><div className="stat"><span>ACTIVE INCIDENTS</span><strong>04</strong><small className="up">+1 <i>since yesterday</i></small></div><div className="stat"><span>DETECTED SLICK AREA</span><strong>12.8 <small>km²</small></strong><small className="up">+3.2% <i>last 6 hours</i></small></div><div className="stat"><span>VESSELS IN ENVELOPE</span><strong>17</strong><small><i>3 high priority</i></small></div><div className="stat"><span>MODEL CONFIDENCE</span><strong>96.4<small>%</small></strong><small className="up">+0.8% <i>vs. last run</i></small></div></section>

        <section className="workspace-grid">
          <div className="map-panel panel"><div className="panel-heading"><div><span className="section-kicker">01 / DETECTION &amp; TRACKING</span><h2>Incident map</h2></div><div className="map-actions"><button className="icon-button">−</button><button className="icon-button">+</button><button className="icon-button">⌖</button></div></div>
            <div className="map-canvas"><div className="map-label label-india">INDIA</div><div className="map-label label-sri">SRI LANKA</div><div className="map-label label-sea">ARABIAN SEA</div><div className="slick slick-one" /><div className="slick slick-two" /><div className="track track-one" /><div className="track track-two" />{layers.vessels && <><div className="vessel v-one">◆</div><div className="vessel v-two">◆</div><div className="vessel v-three">◆</div></>}{layers.currents && <><div className="current c-one">›››››</div><div className="current c-two">›››››</div></>}<div className="map-tooltip"><span className="pulse" /><div><b>INC-240824-01</b><small>Oil slick detected</small></div><strong>HIGH</strong></div><div className="coordinates">14° 32' N &nbsp; 68° 18' E</div><div className="north">N<br /><span>↑</span></div></div>
            <div className="map-footer"><div className="layer-toggles"><label><input type="checkbox" checked={layers.sar} onChange={() => toggleLayer('sar')} /><span className="swatch sar" /> SAR imagery</label><label><input type="checkbox" checked={layers.slick} onChange={() => toggleLayer('slick')} /><span className="swatch slick-swatch" /> Slick overlay</label><label><input type="checkbox" checked={layers.vessels} onChange={() => toggleLayer('vessels')} /><span className="swatch vessel-swatch" /> Vessels</label><label><input type="checkbox" checked={layers.currents} onChange={() => toggleLayer('currents')} /><span className="swatch current-swatch" /> Currents</label></div><span className="map-source">© OpenSeaMap &nbsp; / &nbsp; Sentinel-1 GRD</span></div>
          </div>

          <aside className="side-column"><div className="panel signal-panel"><div className="panel-heading"><div><span className="section-kicker">02 / PRIORITY QUEUE</span><h2>Suspect vessels <span className="count">03</span></h2></div><button className="more">•••</button></div><div className="vessel-list">{vessels.map((vessel, index) => <button className={`vessel-row ${selectedVessel === index ? 'selected' : ''}`} key={vessel.mmsi} onClick={() => setSelectedVessel(index)}><span className={`rank ${vessel.color}`}>0{index + 1}</span><div className="vessel-info"><b>{vessel.name}</b><small>MMSI {vessel.mmsi} &nbsp;·&nbsp; {vessel.flag}</small><span className={`vessel-note ${vessel.color}`}>{vessel.meta}</span></div><span className={`score ${vessel.color}`}>{vessel.score}<small>/100</small></span></button>)}</div><button className="full-list">View all vessel tracks <span>→</span></button></div><div className="panel alert-panel"><span className="alert-icon">!</span><div><b>Dark vessel detected</b><p>Unidentified hull in SAR scene. AIS match pending.</p><small>2 minutes ago</small></div><button className="close-alert">×</button></div></aside>
        </section>

        <section className="timeline panel"><div className="timeline-head"><div><span className="section-kicker">03 / DRIFT SIMULATION</span><h2>Hindcast &amp; forecast</h2></div><div className="timeline-meta"><span className="legend"><i className="hindcast" /> Hindcast</span><span className="legend"><i className="forecast" /> Forecast</span><b>UTC</b></div></div><div className="timeline-body"><button className="play" onClick={() => setPlaying(!playing)}>{playing ? 'Ⅱ' : '▶'}</button><div className="scrubber"><div className="scrub-line"><span className="scrub-progress" style={{ width: playing ? '68%' : '44%' }} /><i className="scrub-knob" style={{ left: playing ? '68%' : '44%' }} /></div><div className="dates"><span>22 AUG<br /><b>00:00</b></span><span>23 AUG<br /><b>00:00</b></span><span className="now">24 AUG<br /><b>08:42</b></span><span>25 AUG<br /><b>00:00</b></span><span>26 AUG<br /><b>00:00</b></span></div></div><button className="speed">1× <span>⌄</span></button></div></section>
      </main><footer><span>OCEANTRACE OPS v1.8.2</span><span>ALL SYSTEMS NOMINAL <i /></span><span>LAST SYNC 08:44:12 UTC</span></footer>
    </div>
  )
}

export default App
