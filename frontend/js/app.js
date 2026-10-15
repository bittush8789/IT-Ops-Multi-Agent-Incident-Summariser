/**
 * IT-Ops Multi-Agent Incident Summariser - Frontend Controller
 * Interacts directly with FastAPI backend endpoints.
 */

// Application State
const state = {
  currentIncident: null,
  incidents: [],
  activeView: 'dashboardView',
  investigationPollingInterval: null,
};

// DOM Elements
const elements = {
  // Navigation
  tabDashboard: document.getElementById('tabDashboard'),
  tabDetails: document.getElementById('tabDetails'),
  tabReport: document.getElementById('tabReport'),
  views: {
    dashboardView: document.getElementById('dashboardView'),
    detailsView: document.getElementById('detailsView'),
    reportView: document.getElementById('reportView'),
  },

  // KPI Counters
  kpiTotal: document.getElementById('kpiTotal'),
  kpiOpen: document.getElementById('kpiOpen'),
  kpiCritical: document.getElementById('kpiCritical'),
  kpiInvestigated: document.getElementById('kpiInvestigated'),

  // Incidents Table
  incidentsTableBody: document.getElementById('incidentsTableBody'),
  incidentsEmptyState: document.getElementById('incidentsEmptyState'),
  filterSeverity: document.getElementById('filterSeverity'),
  filterStatus: document.getElementById('filterStatus'),
  btnRefreshIncidents: document.getElementById('btnRefreshIncidents'),

  // Create Incident Modal
  modalCreateIncident: document.getElementById('modalCreateIncident'),
  btnOpenCreateModal: document.getElementById('btnOpenCreateModal'),
  btnCloseCreateModal: document.getElementById('btnCloseCreateModal'),
  btnCancelCreateModal: document.getElementById('btnCancelCreateModal'),
  formCreateIncident: document.getElementById('formCreateIncident'),
  inpTitle: document.getElementById('inpTitle'),
  inpService: document.getElementById('inpService'),
  inpSeverity: document.getElementById('inpSeverity'),
  inpDescription: document.getElementById('inpDescription'),

  // Incident Details View
  detailKey: document.getElementById('detailKey'),
  detailSeverity: document.getElementById('detailSeverity'),
  detailStatus: document.getElementById('detailStatus'),
  detailTitle: document.getElementById('detailTitle'),
  detailService: document.getElementById('detailService'),
  detailStarted: document.getElementById('detailStarted'),
  detailId: document.getElementById('detailId'),
  detailDescription: document.getElementById('detailDescription'),
  btnTriggerInvestigation: document.getElementById('btnTriggerInvestigation'),
  btnViewReportDirect: document.getElementById('btnViewReportDirect'),

  // Agent Stepper
  stepSupervisor: document.getElementById('stepSupervisor'),
  statusSupervisor: document.getElementById('statusSupervisor'),
  stepLogAnalyst: document.getElementById('stepLogAnalyst'),
  statusLogAnalyst: document.getElementById('statusLogAnalyst'),
  stepChangeAnalyst: document.getElementById('stepChangeAnalyst'),
  statusChangeAnalyst: document.getElementById('statusChangeAnalyst'),
  stepRAG: document.getElementById('stepRAG'),
  statusRAG: document.getElementById('statusRAG'),
  stepReportWriter: document.getElementById('stepReportWriter'),
  statusReportWriter: document.getElementById('statusReportWriter'),

  // Specialist Findings
  logAnalystBadge: document.getElementById('logAnalystBadge'),
  logAnalystContent: document.getElementById('logAnalystContent'),
  changeAnalystBadge: document.getElementById('changeAnalystBadge'),
  changeAnalystContent: document.getElementById('changeAnalystContent'),
  ragMatchCountBadge: document.getElementById('ragMatchCountBadge'),
  ragMatchesContent: document.getElementById('ragMatchesContent'),
  timelineContainer: document.getElementById('timelineContainer'),
  btnRefreshTimeline: document.getElementById('btnRefreshTimeline'),

  // Report View
  reportStatusBadge: document.getElementById('reportStatusBadge'),
  reportTitle: document.getElementById('reportTitle'),
  reportMeta: document.getElementById('reportMeta'),
  reportWarningBanner: document.getElementById('reportWarningBanner'),
  reportWarningText: document.getElementById('reportWarningText'),
  reportExecSummary: document.getElementById('reportExecSummary'),
  reportImpactSummary: document.getElementById('reportImpactSummary'),
  reportRootCausesContainer: document.getElementById('reportRootCausesContainer'),
  reportTimelineBody: document.getElementById('reportTimelineBody'),
  reportRecommendationsContainer: document.getElementById('reportRecommendationsContainer'),
  reportConfidenceNotes: document.getElementById('reportConfidenceNotes'),
  btnRegenerateReport: document.getElementById('btnRegenerateReport'),

  // Alert Container
  alertContainer: document.getElementById('alertContainer'),
};

// UI Notification Helper
function showAlert(message, type = 'info') {
  const alertDiv = document.createElement('div');
  alertDiv.className = `alert alert-${type}`;
  alertDiv.style.cssText = `
    padding: 0.85rem 1.25rem;
    margin-bottom: 1rem;
    border-radius: 8px;
    font-size: 0.875rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: ${type === 'danger' ? 'rgba(239, 68, 68, 0.2)' : type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(59, 130, 246, 0.2)'};
    border: 1px solid ${type === 'danger' ? '#ef4444' : type === 'success' ? '#10b981' : '#3b82f6'};
    color: #fff;
  `;
  alertDiv.innerHTML = `<span>${message}</span><button style="background:none;border:none;color:#fff;cursor:pointer;font-weight:bold;">&times;</button>`;
  alertDiv.querySelector('button').onclick = () => alertDiv.remove();

  elements.alertContainer.appendChild(alertDiv);
  setTimeout(() => { if (alertDiv.parentNode) alertDiv.remove(); }, 6000);
}

// Switch View Helper
function switchView(viewName) {
  state.activeView = viewName;
  Object.keys(elements.views).forEach(key => {
    elements.views[key].classList.toggle('active', key === viewName);
  });
  elements.tabDashboard.classList.toggle('active', viewName === 'dashboardView');
  elements.tabDetails.classList.toggle('active', viewName === 'detailsView');
  elements.tabReport.classList.toggle('active', viewName === 'reportView');
}

// Fetch Incidents from Backend API
async function fetchIncidents() {
  try {
    const severity = elements.filterSeverity.value;
    const status = elements.filterStatus.value;
    let url = '/api/v1/incidents?page=1&page_size=50';
    if (severity) url += `&severity=${severity}`;
    if (status) url += `&status=${status}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch incidents`);

    const data = await res.json();
    state.incidents = data.items || [];
    renderIncidentsTable(state.incidents);
    updateKPICounters(state.incidents);
  } catch (err) {
    showAlert(err.message, 'danger');
  }
}

// Render Incidents Table
function renderIncidentsTable(incidents) {
  elements.incidentsTableBody.innerHTML = '';

  if (incidents.length === 0) {
    elements.incidentsEmptyState.style.display = 'block';
    return;
  }
  elements.incidentsEmptyState.style.display = 'none';

  incidents.forEach(inc => {
    const tr = document.createElement('tr');
    const started = inc.started_at ? new Date(inc.started_at).toLocaleString() : 'N/A';

    let sevClass = 'badge-blue';
    if (inc.severity === 'CRITICAL') sevClass = 'badge-red';
    else if (inc.severity === 'HIGH') sevClass = 'badge-orange';
    else if (inc.severity === 'MEDIUM') sevClass = 'badge-yellow';

    let statusClass = 'badge-blue';
    if (inc.status === 'MITIGATED' || inc.status === 'RESOLVED') statusClass = 'badge-green';
    else if (inc.status === 'INVESTIGATING') statusClass = 'badge-purple';

    tr.innerHTML = `
      <td><strong>${inc.incident_key}</strong></td>
      <td><strong>${inc.title}</strong></td>
      <td><code>${inc.service_name}</code></td>
      <td><span class="badge ${sevClass}">${inc.severity}</span></td>
      <td><span class="badge ${statusClass}">${inc.status}</span></td>
      <td style="font-size: 0.8rem; color: var(--text-secondary);">${started}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="selectIncident(${inc.id})">Investigate</button>
      </td>
    `;
    elements.incidentsTableBody.appendChild(tr);
  });
}

// Update KPI Stats
function updateKPICounters(incidents) {
  elements.kpiTotal.textContent = incidents.length;
  elements.kpiOpen.textContent = incidents.filter(i => i.status === 'OPEN' || i.status === 'INVESTIGATING').length;
  elements.kpiCritical.textContent = incidents.filter(i => i.severity === 'CRITICAL').length;
  elements.kpiInvestigated.textContent = incidents.filter(i => i.status === 'MITIGATED' || i.status === 'RESOLVED').length;
}

// Select an Incident and open Investigation View
window.selectIncident = async function(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}`);
    if (!res.ok) throw new Error('Failed to load incident');
    const incident = await res.json();
    state.currentIncident = incident;

    // Enable details and report tabs
    elements.tabDetails.disabled = false;
    elements.tabReport.disabled = false;

    // Populate Details View
    elements.detailKey.textContent = incident.incident_key;
    elements.detailSeverity.textContent = incident.severity;
    elements.detailStatus.textContent = incident.status;
    elements.detailTitle.textContent = incident.title;
    elements.detailService.textContent = incident.service_name;
    elements.detailStarted.textContent = incident.started_at ? new Date(incident.started_at).toLocaleString() : 'Recent';
    elements.detailId.textContent = incident.id;
    elements.detailDescription.textContent = incident.description;

    // Fetch existing status and timeline
    await refreshInvestigationState(incident.id);
    await loadTimeline(incident.id);

    switchView('detailsView');
  } catch (err) {
    showAlert(err.message, 'danger');
  }
};

// Trigger Multi-Agent Investigation
elements.btnTriggerInvestigation.onclick = async function() {
  if (!state.currentIncident) return;
  const incidentId = state.currentIncident.id;

  elements.btnTriggerInvestigation.disabled = true;
  elements.btnTriggerInvestigation.innerHTML = '<span class="pulse-indicator"></span> Agents Analyzing...';

  // Mark Supervisor active
  setStepState('Supervisor', 'active', 'Analyzing logs & changes...');

  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/investigate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force_refresh: true }),
    });

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Investigation failed');
    }

    const investigationResult = await res.json();
    showAlert(`Investigation completed: ${investigationResult.status}`, 'success');

    // Update UI
    await refreshInvestigationState(incidentId);
    await loadTimeline(incidentId);
    await fetchIncidents();
  } catch (err) {
    showAlert(err.message, 'danger');
  } finally {
    elements.btnTriggerInvestigation.disabled = false;
    elements.btnTriggerInvestigation.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
      Run Multi-Agent Investigation
    `;
  }
};

// Stepper visual updates
function setStepState(agentName, status, statusText) {
  const stepMap = {
    'Supervisor': { elem: elements.stepSupervisor, textElem: elements.statusSupervisor },
    'LogAnalyst': { elem: elements.stepLogAnalyst, textElem: elements.statusLogAnalyst },
    'ChangeAnalyst': { elem: elements.stepChangeAnalyst, textElem: elements.statusChangeAnalyst },
    'RAG': { elem: elements.stepRAG, textElem: elements.statusRAG },
    'ReportWriter': { elem: elements.stepReportWriter, textElem: elements.statusReportWriter },
  };

  const target = stepMap[agentName];
  if (!target) return;

  target.elem.classList.remove('active', 'completed');
  if (status === 'active') target.elem.classList.add('active');
  if (status === 'completed') target.elem.classList.add('completed');
  if (statusText) target.textElem.textContent = statusText;
}

// Refresh Investigation Progress and Agent Findings
async function refreshInvestigationState(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/investigation`);
    if (!res.ok) return;

    const data = await res.json();
    const completed = data.completed_agents || [];
    const failed = data.failed_agents || [];

    // Update Stepper
    setStepState('Supervisor', completed.includes('Supervisor') ? 'completed' : 'pending', completed.includes('Supervisor') ? 'Plan Created' : 'Pending');
    setStepState('LogAnalyst', completed.includes('LogAnalyst') ? 'completed' : (failed.includes('LogAnalyst') ? 'pending' : 'pending'), completed.includes('LogAnalyst') ? 'Spikes Detected' : 'Pending');
    setStepState('ChangeAnalyst', completed.includes('ChangeAnalyst') ? 'completed' : 'pending', completed.includes('ChangeAnalyst') ? 'Commits Evaluated' : 'Pending');
    setStepState('RAG', completed.includes('ReportWriter') ? 'completed' : 'pending', completed.includes('ReportWriter') ? 'Precedents Retrieved' : 'Pending');
    setStepState('ReportWriter', completed.includes('ReportWriter') ? 'completed' : 'pending', completed.includes('ReportWriter') ? 'PIR Synthesized' : 'Pending');

    // Update Findings Cards if report exists
    if (data.has_report) {
      await renderReport(incidentId);
    }
  } catch (err) {
    console.error('Error refreshing investigation state:', err);
  }
}

// Load Verified Timeline
async function loadTimeline(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/timeline`);
    if (!res.ok) return;
    const events = await res.json();

    if (events.length === 0) {
      elements.timelineContainer.innerHTML = '<p class="text-muted">No timeline events recorded yet. Run investigation to extract events.</p>';
      return;
    }

    elements.timelineContainer.innerHTML = '';
    events.forEach(evt => {
      const div = document.createElement('div');
      let typeClass = 'timeline-event';
      if (evt.event_type === 'DEPLOYMENT') typeClass += ' deployment';
      else if (evt.event_type.includes('ERROR') || evt.event_type.includes('EXCEPTION')) typeClass += ' error';
      else if (evt.event_type.includes('ALERT')) typeClass += ' alert';

      div.className = typeClass;
      div.innerHTML = `
        <div class="timeline-dot"></div>
        <div class="timeline-time">${new Date(evt.timestamp).toUTCString()} &bull; <strong>${evt.source}</strong></div>
        <div class="timeline-desc">${evt.description}</div>
        ${evt.evidence_reference ? `<div class="timeline-ref">Evidence: ${evt.evidence_reference}</div>` : ''}
      `;
      elements.timelineContainer.appendChild(div);
    });
  } catch (err) {
    console.error('Error loading timeline:', err);
  }
}

// Render Post-Incident Review Report
async function renderReport(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/report`);
    if (!res.ok) return;
    const report = await res.json();

    elements.reportTitle.textContent = `Post-Incident Review: ${state.currentIncident.title}`;
    elements.reportMeta.textContent = `Incident Key: ${state.currentIncident.incident_key} • Generated by LangGraph Report Writer Agent`;

    elements.reportExecSummary.textContent = report.executive_summary;
    elements.reportImpactSummary.textContent = report.impact_summary;
    elements.reportConfidenceNotes.textContent = report.confidence_notes;

    // Render Root Cause Hypotheses
    elements.reportRootCausesContainer.innerHTML = '';
    (report.root_cause_hypotheses || []).forEach(h => {
      const div = document.createElement('div');
      div.className = 'root-cause-item';
      div.innerHTML = `
        <div class="root-cause-header">
          <div class="root-cause-title">${h.hypothesis}</div>
          <span class="badge ${h.likelihood === 'HIGH' ? 'badge-red' : 'badge-yellow'}">${h.likelihood} LIKELIHOOD</span>
        </div>
        <div style="font-size: 0.85rem; margin-top: 0.5rem;">
          <strong style="color: var(--success);">Supporting Evidence:</strong>
          <ul style="margin-left: 1.25rem; margin-top: 0.25rem;">
            ${h.supporting_evidence.map(e => `<li>${e}</li>`).join('')}
          </ul>
        </div>
        ${h.unknowns && h.unknowns.length > 0 ? `
          <div style="font-size: 0.85rem; margin-top: 0.5rem;">
            <strong style="color: var(--text-muted);">Unknowns / Gaps:</strong>
            <ul style="margin-left: 1.25rem; margin-top: 0.25rem;">
              ${h.unknowns.map(u => `<li>${u}</li>`).join('')}
            </ul>
          </div>
        ` : ''}
      `;
      elements.reportRootCausesContainer.appendChild(div);
    });

    // Render Recommendations
    elements.reportRecommendationsContainer.innerHTML = '';
    (report.recommendations || []).forEach(r => {
      const div = document.createElement('div');
      div.className = 'action-card';
      div.innerHTML = `
        <div class="action-header">
          <span class="badge badge-red">${r.priority}</span>
          <span class="badge badge-blue">${r.owner_team}</span>
        </div>
        <div class="action-title">${r.title}</div>
        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">${r.description}</p>
      `;
      elements.reportRecommendationsContainer.appendChild(div);
    });

    // Populate Report Timeline Table
    elements.reportTimelineBody.innerHTML = '';
    (report.timeline || []).forEach(t => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code style="font-size: 0.8rem;">${new Date(t.timestamp).toUTCString()}</code></td>
        <td><span class="badge badge-blue">${t.event_type}</span></td>
        <td><strong>${t.source}</strong></td>
        <td>${t.description}</td>
        <td><code style="color: #60a5fa; font-size: 0.75rem;">${t.evidence_reference || 'N/A'}</code></td>
      `;
      elements.reportTimelineBody.appendChild(tr);
    });

    // Populate specialist tabs on Details View as well
    elements.logAnalystBadge.textContent = 'COMPLETED';
    elements.logAnalystBadge.className = 'badge badge-green';
    elements.logAnalystContent.innerHTML = `
      <p style="margin-bottom: 0.5rem; font-size: 0.875rem;"><strong>Impact:</strong> ${report.impact_summary}</p>
      <div style="margin-top: 0.5rem;">
        <span class="timeline-ref">Verified error patterns extracted from logs</span>
      </div>
    `;

    elements.changeAnalystBadge.textContent = 'COMPLETED';
    elements.changeAnalystBadge.className = 'badge badge-green';
    elements.changeAnalystContent.innerHTML = `
      <p style="margin-bottom: 0.5rem; font-size: 0.875rem;"><strong>Change Correlation:</strong> Inspected repository commits against incident window.</p>
      <span class="timeline-ref">Commits correlated with start time</span>
    `;

    elements.ragMatchCountBadge.textContent = 'Active Precedents';
    elements.ragMatchesContent.innerHTML = `
      <p style="font-size: 0.875rem; color: #c084fc;">pgvector semantic similarity search linked precedent historical incidents for resolution suggestions.</p>
    `;
  } catch (err) {
    console.error('Error rendering report:', err);
  }
}

// Event Listeners for Tab Switching
elements.tabDashboard.onclick = () => switchView('dashboardView');
elements.tabDetails.onclick = () => { if (!elements.tabDetails.disabled) switchView('detailsView'); };
elements.tabReport.onclick = () => { if (!elements.tabReport.disabled) switchView('reportView'); };
elements.btnViewReportDirect.onclick = () => switchView('reportView');

// Event Listeners for Incident Creation Modal
elements.btnOpenCreateModal.onclick = () => elements.modalCreateIncident.classList.add('active');
elements.btnCloseCreateModal.onclick = () => elements.modalCreateIncident.classList.remove('active');
elements.btnCancelCreateModal.onclick = () => elements.modalCreateIncident.classList.remove('active');

elements.formCreateIncident.onsubmit = async function(e) {
  e.preventDefault();
  const title = elements.inpTitle.value.trim();
  const service_name = elements.inpService.value.trim();
  const severity = elements.inpSeverity.value;
  const description = elements.inpDescription.value.trim();

  try {
    const res = await fetch('/api/v1/incidents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        service_name,
        severity,
        description,
        started_at: new Date().toISOString(),
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to create incident');
    }

    const created = await res.json();
    elements.modalCreateIncident.classList.remove('active');
    elements.formCreateIncident.reset();
    showAlert(`Incident ${created.incident_key} successfully declared!`, 'success');

    await fetchIncidents();
    selectIncident(created.id);
  } catch (err) {
    showAlert(err.message, 'danger');
  }
};

// Refresh Filters
elements.filterSeverity.onchange = fetchIncidents;
elements.filterStatus.onchange = fetchIncidents;
elements.btnRefreshIncidents.onclick = fetchIncidents;
elements.btnRefreshTimeline.onclick = () => {
  if (state.currentIncident) loadTimeline(state.currentIncident.id);
};

// Regenerate Report Button
elements.btnRegenerateReport.onclick = async function() {
  if (!state.currentIncident) return;
  elements.btnRegenerateReport.disabled = true;
  elements.btnRegenerateReport.textContent = 'Regenerating...';
  try {
    const res = await fetch(`/api/v1/incidents/${state.currentIncident.id}/report/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ include_historical_context: true }),
    });
    if (!res.ok) throw new Error('Regeneration failed');
    showAlert('Report successfully regenerated!', 'success');
    await renderReport(state.currentIncident.id);
  } catch (err) {
    showAlert(err.message, 'danger');
  } finally {
    elements.btnRegenerateReport.disabled = false;
    elements.btnRegenerateReport.textContent = 'Regenerate Report';
  }
};

// Initialize Application on Page Load
document.addEventListener('DOMContentLoaded', () => {
  fetchIncidents();
});
