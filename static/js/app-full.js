
const API_BASE = 'http://localhost:5000/api';

// ==================== Initialize after page load ====================
window.addEventListener('load', async function() {

    await initApp();


        window.addEventListener('click', function(e) {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
                if (e.target.id === 'createTaskModal') {
                    cancelTaskVertexSelection(false);
                }
            }
        });
});

const hoverTooltip = document.getElementById('hoverTooltip');
const HOVER_TOOLTIP_OFFSET = 18;


        let mapData = {};


        let currentMap = null;
        let currentMode = 'default'; // default, path, measure, edit
        let editOperation = 'move'; // move, insert, delete
        let canvas = document.getElementById('mapCanvas');
        let ctx = canvas.getContext('2d');
        let mapImage = null;
        let viewScale = 1;
        let viewPan = { x: 0, y: 0 };
        let mapPixelWidth = 0;
        let mapPixelHeight = 0;
        let isPanning = false;
        let lastPanMousePos = { x: 0, y: 0 };


        let showGrid = false;
        let gridSize = 1.0;

        function resizeCanvas() {
            const container = document.getElementById('container');
            if (container) {
                canvas.width = container.clientWidth;
                canvas.height = container.clientHeight;
                redraw();
            }
        }
        window.addEventListener('resize', resizeCanvas);


        let vertices = [];  // { id, x, y, z, type, action, properties }
        let edges = [];     // { id, from, to, direction, length, cost, max_speed, width, action }
        let loadedPaths = [];


        let lastVertex = null;
        let selectedElement = null;
        let hoveredElement = null;
        let hoveredPath = null;
        let hoveredEdge = null;
        let currentMousePos = null;
        let isDragging = false;

        // AGVStatus
        let agvs = [];
        let selectedAgvId = null;
        let selectedTaskId = null;
        let highlightedTaskVertices = { start: null, end: null };
        let activeDrawerTab = 'agv';
        let infoHideTimer = null;
        let agvListLoaded = false;
        let tasks = [];
        let currentScene = null;
        let sceneOptions = [];
        const taskListRenderState = {
            listEl: null,
            elements: new Map(),
            signatures: new Map(),
            order: [],
            dirty: false
        };
        // Action timing
        let batteryConfig = {
            chargeRate: 1.0,      // Charge rate (%/s)
            idleConsumption: 0.1,  // Idle consumption (%/s)
            workingConsumption: 0.5 // Working consumption (%/s)
        };

        let actionConfigs = {
            'pick': { type: 'fixed', value: 5 },
            'drop': { type: 'fixed', value: 5 },
            'dock': { type: 'fixed', value: 5 },
            'charge': { type: 'fixed', value: 60 },
            'enter_elevator': { type: 'fixed', value: 5 },
            'exit_elevator': { type: 'fixed', value: 5 },
            'request_entry': { type: 'random', min: 2, max: 10 },
            'wait_elevator': { type: 'random', min: 5, max: 20 }
        };
        let pendingTaskVertexField = null;
        let previousModeBeforeTaskSelect = null;
        let taskModalHiddenForSelection = false;
        let isAgvMoveMode = false;
        let isAgvPlacementMode = false;
        let pendingAgvPosition = null;
        let draggingAgv = null;
        let agvDragFloor = null;
        const AGV_COLOR_PALETTE = [
            '#FF6B6B',
            '#4ECDC4',
            '#FFD93D',
            '#1A535C',
            '#FF9F1C',
            '#9B5DE5',
            '#00BBF9',
            '#F07167',
            '#2EC4B6',
            '#FF9770'
        ];

        function hashString(str) {
            let hash = 0;
            const text = String(str || '');
            for (let i = 0; i < text.length; i++) {
                hash = ((hash << 5) - hash) + text.charCodeAt(i);
                hash |= 0;
            }
            return hash;
        }

        function getAgvDisplayColor(agv) {
            if (!agv) return '#007bff';
            if (agv.color) return agv.color;
            const key = agv.id || agv.name || Math.random().toString();
            const index = Math.abs(hashString(key)) % AGV_COLOR_PALETTE.length;
            return AGV_COLOR_PALETTE[index];
        }

        function normalizeTask(task) {
            if (!task) return null;
            return {
                id: task.id || generateId('T'),
                name: task.name || 'Unnamed task',
                start_vertex: task.start_vertex || '',
                end_vertex: task.end_vertex || '',
                end_vertices: task.end_vertices || (task.end_vertex ? [task.end_vertex] : []),
                priority: task.priority || 'medium',
                start_time: task.start_time || task.eta || '',
                deadline: task.deadline || '',
                status: task.status || 'pending',
                created_at: task.created_at || new Date().toISOString(),
                agv_id: task.agv_id || null,
                completed_at: task.completed_at || null,
                completed_at_sim: typeof task.completed_at_sim !== 'undefined' ? task.completed_at_sim : null,
                current_end_index: typeof task.current_end_index === 'number' ? task.current_end_index : 0
            };
        }


        let vertexMap = {}; // id -> {x, y, z}
        let edgeMap = {}; // id -> edge


        const EDGE_COLOR_DOUBLE = 'rgba(190, 190, 190, 0.85)';
        const EDGE_COLOR_SINGLE = 'rgba(220, 220, 220, 0.65)';
        const EDGE_ARROW_COLOR_DOUBLE = 'rgba(90, 90, 90, 0.95)';
        const EDGE_ARROW_COLOR_SINGLE = 'rgba(130, 130, 130, 0.9)';

        // Settings
        let snapEnabled = true;
        let snapRadius = 20;
        let measurePoints = [];



        function escapeHtml(value) {
            if (value === null || value === undefined) return '';
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function formatNumberDisplay(value, digits = 2, suffix = '') {
            const num = parseFloat(value);
            if (!Number.isFinite(num)) return '-';
            return `${num.toFixed(digits)}${suffix}`;
        }

        function formatTooltipRow(label, value) {
            return `<div class="tooltip-row"><span class="tooltip-label">${escapeHtml(label)}</span><span class="tooltip-value">${escapeHtml(value)}</span></div>`;
        }

        function summarizeProperties(properties) {
            if (!properties || typeof properties !== 'object') return '';
            const entries = Object.entries(properties);
            if (!entries.length) return '';
            return entries
                .slice(0, 3)
                .map(([key, val]) => `${key}: ${val}`)
                .join(', ');
        }

        function formatDisplayValue(value) {
            if (value === null || value === undefined || value === '') return '-';
            if (typeof value === 'object') {
                try {
                    return JSON.stringify(value);
                } catch (err) {
                    return '-';
                }
            }
            return String(value);
        }

        function lookupVertexById(vertexId, info) {
            if (!vertexId) return null;
            if (vertexMap[vertexId]) return vertexMap[vertexId];
            if (info && info.source === 'loaded' && info.pathIndex !== undefined) {
                const path = loadedPaths[info.pathIndex];
                if (path && path.vertices) {
                    return path.vertices.find(v => v.id === vertexId) || null;
                }
            }
            return vertices.find(v => v.id === vertexId) || null;
        }

        function getEdgeEndpoints(edge, info) {
            return {
                from: lookupVertexById(edge.from, info),
                to: lookupVertexById(edge.to, info)
            };
        }


        function getVertexTypeName(type) {
            const typeMap = {
                'waypoint': 'Waypoint',
                'work_station': 'Work station',
                'elevator_entrance': 'Elevator entrance',
                'charging_station': 'Charging station',
                'standby_point': 'Standby point'
            };
            return typeMap[type] || type || 'Waypoint';
        }

        function buildVertexTooltipContent(info) {
            if (!info || !info.element) return '';
            const vertex = info.element;
            const coordText = `${formatNumberDisplay(vertex.x, 3)}, ${formatNumberDisplay(vertex.y, 3)}, ${vertex.z ?? '-'}`;
            let html = `<div class="tooltip-title">Vertex ${escapeHtml(vertex.id || '')}</div>`;
            html += formatTooltipRow('Type', getVertexTypeName(vertex.type));
            html += formatTooltipRow('Action', vertex.action || 'None');
            html += formatTooltipRow('Coordinates', coordText);
            if (info.source === 'loaded' && info.pathIndex !== undefined) {
                const path = loadedPaths[info.pathIndex];
                if (path && path.name) {
                    html += formatTooltipRow('Path', path.name);
                }
            }
            const propSummary = summarizeProperties(vertex.properties);
            if (propSummary) {
                html += formatTooltipRow('Properties', propSummary);
            }
            return html;
        }

        function buildEdgeTooltipContent(info) {
            if (!info || !info.element) return '';
            const edge = info.element;
            const { from, to } = getEdgeEndpoints(edge, info);
            const lengthValue = edge.length ?? (from && to ? worldDistance(from, to) : null);
            let html = `<div class="tooltip-title">Edge ${escapeHtml(edge.id || '')}</div>`;
            html += formatTooltipRow('From', edge.from || '-');
            html += formatTooltipRow('To', edge.to || '-');
            html += formatTooltipRow('Direction', edge.direction === 'bidirectional' ? 'Bidirectional' : 'Unidirectional');
            html += formatTooltipRow('Length', lengthValue ? formatNumberDisplay(lengthValue, 2, ' m') : '-');
            html += formatTooltipRow('Width', edge.width ? formatNumberDisplay(edge.width, 2, ' m') : '-');
            if (edge.max_speed) {
                html += formatTooltipRow('Speed limit', formatNumberDisplay(edge.max_speed, 2, ' m/s'));
            }
            if (edge.cost) {
                html += formatTooltipRow('Cost', formatDisplayValue(edge.cost));
            }
            if (info.source === 'loaded' && info.pathIndex !== undefined) {
                const path = loadedPaths[info.pathIndex];
                if (path && path.name) {
                    html += formatTooltipRow('Path', path.name);
                }
            }
            return html;
        }

        function buildAgvTooltipContent(agv) {
            if (!agv) return '';
            const pos = agv.position || {};
            const coordText = `${formatNumberDisplay(pos.x, 2)}, ${formatNumberDisplay(pos.y, 2)}, ${pos.z ?? '-'}`;
            const orientationDeg = typeof agv.orientation === 'number'
                ? `${(agv.orientation * 180 / Math.PI).toFixed(0)} deg`
                : '-';
            const task = typeof agv.current_task === 'object'
                ? (agv.current_task.name || agv.current_task.id || 'In progress')
                : (agv.current_task || 'None');
            let html = `<div class="tooltip-title">AGV ${escapeHtml(agv.name || agv.id || '')}</div>`;
            html += formatTooltipRow('ID', agv.id || '-');
            html += formatTooltipRow('Status', agv.status || '-');
            html += formatTooltipRow('Battery', agv.battery !== undefined ? `${formatNumberDisplay(agv.battery, 0, '%')}` : '-');
            html += formatTooltipRow('Position', coordText);
            html += formatTooltipRow('Heading', orientationDeg);
            html += formatTooltipRow('Task', task || 'None');
            return html;
        }

        function updateHoverTooltip(target, evt) {
            if (!hoverTooltip) return;
            if (!target) {
                hideHoverTooltip();
                return;
            }
            let html = '';
            if (target.type === 'vertex') {
                html = buildVertexTooltipContent(target);
            } else if (target.type === 'edge') {
                html = buildEdgeTooltipContent(target);
            } else if (target.type === 'agv') {
                html = buildAgvTooltipContent(target.element);
            }
            if (!html) {
                hideHoverTooltip();
                return;
            }
            hoverTooltip.innerHTML = html;
            hoverTooltip.style.display = 'block';
            const rect = hoverTooltip.getBoundingClientRect();
            let left = evt.clientX + HOVER_TOOLTIP_OFFSET;
            let top = evt.clientY + HOVER_TOOLTIP_OFFSET;
            if (left + rect.width > window.innerWidth - 8) {
                left = evt.clientX - rect.width - HOVER_TOOLTIP_OFFSET;
            }
            if (top + rect.height > window.innerHeight - 8) {
                top = evt.clientY - rect.height - HOVER_TOOLTIP_OFFSET;
            }
            hoverTooltip.style.left = `${Math.max(8, left)}px`;
            hoverTooltip.style.top = `${Math.max(8, top)}px`;
        }

        function hideHoverTooltip() {
            if (hoverTooltip) {
                hoverTooltip.style.display = 'none';
            }
        }


        function generateId(prefix) {
            return `${prefix}${Date.now()}${Math.floor(Math.random() * 1000)}`;
        }


        function pixelToWorld(px, py) {
            const data = mapData[currentMap];

            // Screen Pixels -> Map Image Pixels
            const mapPx = (px - viewPan.x) / viewScale;
            const mapPy = (py - viewPan.y) / viewScale;

            const height = mapPixelHeight || canvas.height;

            const x = mapPx * data.resolution + data.origin.x;
            //const y = -((height - mapPy) * data.resolution + data.origin.y);
            const y = ((height - mapPy) * data.resolution + data.origin.y)
            return { x, y, z: data.floor };
        }


        function worldToPixel(wx, wy) {
            const data = mapData[currentMap];
            const height = mapPixelHeight || canvas.height;

            const px = (wx - data.origin.x) / data.resolution;
            //const py = height + (wy + data.origin.y) / data.resolution;
            const py = height - (wy - data.origin.y) / data.resolution;
            return { x: px, y: py };
        }

        function mapToScreen(mx, my) {
            return {
                x: mx * viewScale + viewPan.x,
                y: my * viewScale + viewPan.y
            };
        }

        function screenToMap(sx, sy) {
            return {
                x: (sx - viewPan.x) / viewScale,
                y: (sy - viewPan.y) / viewScale
            };
        }


        function getCanvasPos(e) {
            const rect = canvas.getBoundingClientRect();
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;
            return {
                x: (e.clientX - rect.left) * scaleX,
                y: (e.clientY - rect.top) * scaleY
            };
        }


        function distance(p1, p2) {
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            return Math.sqrt(dx * dx + dy * dy);
        }


        function worldDistance(p1, p2) {
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            return Math.sqrt(dx * dx + dy * dy);
        }

        function isSceneActive() {
            return !!currentScene;
        }

        function updateSceneIndicator() {
            const indicator = document.getElementById('currentSceneDisplay');
            if (!indicator) return;
            indicator.textContent = currentScene ? `Current scene: ${currentScene}` : 'No active scene';
        }

        async function refreshSceneOptions() {
            try {
                const response = await fetch(`${API_BASE}/scenes`);
                const result = await response.json();
                if (result.success) {
                    sceneOptions = result.scenes || [];
                    const select = document.getElementById('sceneSelect');
                    if (select) {
                        select.innerHTML = sceneOptions.length === 0
                            ? '<option value="">No scenes</option>'
                            : sceneOptions.map(scene => `<option value="${scene.name}">${scene.name} (${scene.path_count || 0} paths)</option>`).join('');
                    }
                }
            } catch (error) {
                console.error('Failed to load scene list:', error);
            }
        }

        async function loadSceneMaps(sceneName) {
            try {
                const response = await fetch(`${API_BASE}/scenes/${sceneName}/maps`);
                const result = await response.json();
                if (result.success) {
                    mapData = result.maps;


                    for (let key in mapData) {
                        const floorVal = parseInt(key);
                        mapData[key].floor = isNaN(floorVal) ? key : floorVal;
                    }

                    const keys = Object.keys(mapData).sort();
                    if (keys.length > 0) {
                        if (!currentMap || !mapData[currentMap]) {
                            currentMap = keys[0];
                        }
                    } else {
                        currentMap = null;
                    }

                    updateMapLayerControls();
                    if (currentMap) loadMap(currentMap);
                }
            } catch (e) {
                console.error('Failed to load map configuration:', e);
            }
        }

        function updateMapLayerControls() {
            const mapSelect = document.getElementById('mapSelect');
            const agvFloor = document.getElementById('agvFloor');

            if (mapSelect) {
                mapSelect.innerHTML = '';
                Object.keys(mapData).sort().forEach(key => {
                    const option = document.createElement('option');
                    option.value = key;
                    option.textContent = `${key} floor`;
                    if (key === currentMap) option.selected = true;
                    mapSelect.appendChild(option);
                });

                // Update listener
                mapSelect.onchange = function() {
                    currentMap = this.value;
                    loadMap(currentMap);
                };
            }

            if (agvFloor) {
                agvFloor.innerHTML = '';
                Object.keys(mapData).sort().forEach(key => {
                    const option = document.createElement('option');
                    option.value = mapData[key].floor;
                    option.textContent = `${key} floor`;
                    agvFloor.appendChild(option);
                });
            }
        }

        async function persistSceneData() {


            console.log('persistSceneData is deprecated; use Save scene');
        }

        async function saveSceneExplicit() {
            if (!currentScene) {
                alert('Load a scene first');
                return;
            }


            if (simRunning) {
                alert('The scene cannot be saved while simulation is running');
                return;
            }

            try {

                await fetch(`${API_BASE}/scenes/${encodeURIComponent(currentScene)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        paths: loadedPaths,
                        agvs: agvs,
                        tasks: tasks,
                        actionConfigs: actionConfigs,
                        batteryConfig: batteryConfig
                    })
                });


                const response = await fetch(`${API_BASE}/scenes/${encodeURIComponent(currentScene)}/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();
                if (result.success) {
                    updateInfo('Scene saved');
                } else {
                    alert('Scene save failed: ' + result.error);
                }
            } catch (error) {
                console.error('Scene save error:', error);
                alert('Scene save failed; check the server log');
            }
        }

        async function applySceneData(scene) {
            await loadSceneMaps(scene.name);
            currentScene = scene.name;


            const loadSceneBtn = document.getElementById('loadSceneBtn');
            if (loadSceneBtn) {
                loadSceneBtn.disabled = true;
                loadSceneBtn.style.opacity = '0.5';
                loadSceneBtn.style.cursor = 'not-allowed';
            }

            setAgvCollection(scene.agvs || []);
            agvListLoaded = true;
            selectedAgvId = null;
            tasks = (scene.tasks || []).map(normalizeTask).filter(Boolean);
            resetTaskListRenderState();
            loadedPaths = scene.paths || [];


            if (scene.actionConfigs) {
                actionConfigs = scene.actionConfigs;
            } else {

                actionConfigs = {
                    'pick': { type: 'fixed', value: 5 },
                    'drop': { type: 'fixed', value: 5 },
                    'dock': { type: 'fixed', value: 5 },
                    'charge': { type: 'fixed', value: 60 },
                    'enter_elevator': { type: 'fixed', value: 5 },
                    'exit_elevator': { type: 'fixed', value: 5 },
                    'request_entry': { type: 'random', min: 2, max: 10 },
                    'wait_elevator': { type: 'random', min: 5, max: 20 }
                };
            }


            if (scene.batteryConfig) {
                batteryConfig = scene.batteryConfig;
            } else {
                batteryConfig = {
                    chargeRate: 1.0,
                    idleConsumption: 0.1,
                    workingConsumption: 0.5
                };
            }

            // Build Maps
            vertexMap = {};
            edgeMap = {};
            loadedPaths.forEach(path => {
                if(path.vertices) path.vertices.forEach(v => vertexMap[v.id] = v);
                if(path.edges) path.edges.forEach(e => edgeMap[e.id] = e);
            });

            updateSceneIndicator();
            updateAgvList();
            updateTaskListPanel();
            redraw();
        }

        async function handleCreateSceneConfirm() {
            const input = document.getElementById('sceneNameInput');
            if (!input) return;
            const name = input.value.trim();
            if (!name) {
                alert('Enter a scene name');
                return;
            }
            try {
                const response = await fetch(`${API_BASE}/scenes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        paths: loadedPaths,
                        agvs: agvs,
                        tasks: tasks,
                        actionConfigs: actionConfigs
                    })
                });
                const result = await response.json();
                if (result.success) {
                    applySceneData(result.scene);
                    input.value = '';
                    closeSceneModal('createSceneModal');
                    updateInfo(`Scene created: ${name}`);
                    refreshSceneOptions();
                } else {
                    alert('Scene creation failed: ' + result.error);
                }
            } catch (error) {
                console.error('Scene creation failed: ', error);
                alert('Scene creation failed; check the server log');
            }
        }

        async function handleLoadSceneConfirm() {
            const select = document.getElementById('sceneSelect');
            if (!select) return;
            const name = select.value;
            if (!name) {
                alert('Select a scene');
                return;
            }
            try {
                const response = await fetch(`${API_BASE}/scenes/${encodeURIComponent(name)}`);
                const result = await response.json();
                if (result.success) {
                    applySceneData(result.scene);
                    closeSceneModal('loadSceneModal');
                    updateInfo(`Scene loaded: ${name}`);
                } else {
                    alert('Scene load failed: ' + result.error);
                }
            } catch (error) {
                console.error('Scene load failed:', error);
                alert('Scene load failed; check the server log');
            }
        }

        async function handleGenerateTaskConfirm() {
            if (!currentScene) {
                alert('Load a scene first');
                return;
            }

            const count = parseInt(document.getElementById('generateTaskCount').value);
            const duration = parseFloat(document.getElementById('generateTaskDuration').value);
            const priorityLow = parseInt(document.getElementById('generateTaskPriorityLow').value);
            const priorityMedium = parseInt(document.getElementById('generateTaskPriorityMedium').value);
            const priorityHigh = parseInt(document.getElementById('generateTaskPriorityHigh').value);
            const deadlineMin = parseFloat(document.getElementById('generateTaskDeadlineMin').value);
            const deadlineMax = parseFloat(document.getElementById('generateTaskDeadlineMax').value);
            const endMin = parseInt(document.getElementById('generateTaskEndMin')?.value ?? '1');
            const endMax = parseInt(document.getElementById('generateTaskEndMax')?.value ?? '1');


            if (isNaN(count) || count < 1 || count > 1000) {
                alert('Task count must be between 1 and 100');
                return;
            }
            if (isNaN(duration) || duration <= 0) {
                alert('Time range must be greater than zero');
                return;
            }
            const prioritySum = priorityLow + priorityMedium + priorityHigh;
            if (prioritySum !== 100) {
                if (!confirm(`Priority percentages total ${prioritySum}%, not 100%. Continue with random priorities?`)) {
                    return;
                }
            }
            if (deadlineMin < 0 || deadlineMax < 0 || deadlineMin > deadlineMax) {
                alert('Invalid deadline range: minimum must be non-negative and no greater than maximum');
                return;
            }
            if (Number.isNaN(endMin) || Number.isNaN(endMax) || endMin < 0 || endMax < 0 || endMin > endMax || endMax > 5) {
                alert('Invalid destination count: use integers from 0 to 5, with minimum no greater than maximum');
                return;
            }

            try {
                const requestBody = {
                    count: count,
                    duration: duration
                };


                if (prioritySum === 100) {
                    requestBody.priority_distribution = {
                        low: priorityLow,
                        medium: priorityMedium,
                        high: priorityHigh
                    };
                }


                if (deadlineMin > 0 && deadlineMax > 0) {
                    requestBody.deadline_range = {
                        min: deadlineMin,
                        max: deadlineMax
                    };
                }


                requestBody.end_vertex_count_range = {
                    min: endMin,
                    max: endMax
                };

                const response = await fetch(`${API_BASE}/scenes/${currentScene}/tasks/generate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });
                const result = await response.json();
                if (result.success) {
                    closeGenerateTaskModal();
                    alert(`Generated ${result.tasks.length} tasks`);

                    if (result.scene) {
                        await applySceneData(result.scene);
                        updateInfo(`Generated ${result.tasks.length} tasks`);
                    } else {

                        try {
                            const sceneResponse = await fetch(`${API_BASE}/scenes/${encodeURIComponent(currentScene)}`);
                            const sceneResult = await sceneResponse.json();
                            if (sceneResult.success) {
                                await applySceneData(sceneResult.scene);
                                updateInfo(`Scene refreshed: ${currentScene}`);
                            }
                        } catch (error) {
                            console.error('Failed to refresh scene:', error);
                            alert('Tasks generated, but refreshing the scene failed; reload manually');
                        }
                    }
                } else {
                    alert('Generation failed: ' + result.error);
                }
            } catch (error) {
                console.error('Failed to generate tasks:', error);
                alert('Request failed: ' + error.message);
            }
        }

        async function exitScene() {
            if (!currentScene) {
                updateInfo('No active scene');
                return;
            }


            if (simRunning) {
                await stopSimulation();
            }


            try {
                await fetch(`${API_BASE}/simulation/reset`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ clear_all: true })
                });
            } catch (e) {
                console.error("Failed to clear backend state:", e);
            }

            currentScene = null;
            tasks = [];
            resetTaskListRenderState();
            loadedPaths = [];
            agvs = [];
            agvListLoaded = false;
            selectedAgvId = null;
            selectedTaskId = null;
            highlightedTaskVertices = { start: null, end: null };


            const loadSceneBtn = document.getElementById('loadSceneBtn');
            if (loadSceneBtn) {
                loadSceneBtn.disabled = false;
                loadSceneBtn.style.opacity = '1';
                loadSceneBtn.style.cursor = 'pointer';
            }


            vertexMap = {};
            edgeMap = {};


            selectedElement = null;
            hoveredElement = null;
            hoveredPath = null;
            hoveredEdge = null;
            lastVertex = null;
            measurePoints = [];
            selectedTaskId = null;
            highlightedTaskVertices = { start: null, end: null };

            updateSceneIndicator();
            updateAgvList();
            updateTaskListPanel();
            redraw();
            updateInfo('Exited scene mode');
        }


        function findNearbyVertexForSnap(pixelPos, radius) {
            const currentFloor = mapData[currentMap].floor;
            let closestVertex = null;
            let closestDistance = Infinity;


            for (let vertex of vertices) {
                if (vertex.z !== currentFloor) continue;
                const vMap = worldToPixel(vertex.x, vertex.y);
                const vPixel = mapToScreen(vMap.x, vMap.y);
                const dist = distance(pixelPos, vPixel);
                if (dist < radius && dist < closestDistance) {
                    closestDistance = dist;
                    closestVertex = vertex;
                }
            }


            for (let path of loadedPaths) {
                if (path.floor !== currentFloor) continue;
                if (!path.vertices) continue;

                for (let vertex of path.vertices) {
                    const vMap = worldToPixel(vertex.x, vertex.y);
                const vPixel = mapToScreen(vMap.x, vMap.y);
                    const dist = distance(pixelPos, vPixel);
                    if (dist < radius && dist < closestDistance) {
                        closestDistance = dist;
                        closestVertex = vertex;
                    }
                }
            }


            return closestDistance < radius ? closestVertex : null;
        }


        function findElementAt(pixelPos) {
            const currentFloor = mapData[currentMap].floor;


            for (let vertex of vertices) {
                if (vertex.z !== currentFloor) continue;
                const vMap = worldToPixel(vertex.x, vertex.y);
                const vPixel = mapToScreen(vMap.x, vMap.y);
                if (distance(pixelPos, vPixel) < 10) {
                    return { type: 'vertex', element: vertex, source: 'current' };
                }
            }


            for (let pathIndex = 0; pathIndex < loadedPaths.length; pathIndex++) {
                const path = loadedPaths[pathIndex];
                if (path.floor !== currentFloor) continue;
                if (!path.vertices) continue;

                for (let vertex of path.vertices) {
                    const vMap = worldToPixel(vertex.x, vertex.y);
                const vPixel = mapToScreen(vMap.x, vMap.y);
                    if (distance(pixelPos, vPixel) < 10) {
                        return { type: 'vertex', element: vertex, source: 'loaded', pathIndex: pathIndex };
                    }
                }
            }


            for (let edge of edges) {
                const fromVertex = vertices.find(v => v.id === edge.from);
                const toVertex = vertices.find(v => v.id === edge.to);
                if (!fromVertex || !toVertex) continue;
                if (fromVertex.z !== currentFloor) continue;

                const p1Map = worldToPixel(fromVertex.x, fromVertex.y);
                const p2Map = worldToPixel(toVertex.x, toVertex.y);
                const p1 = mapToScreen(p1Map.x, p1Map.y);
                const p2 = mapToScreen(p2Map.x, p2Map.y);

                const dist = distanceToSegment(pixelPos, p1, p2);
                if (dist < 8) {
                    return { type: 'edge', element: edge, source: 'current' };
                }
            }


            for (let pathIndex = 0; pathIndex < loadedPaths.length; pathIndex++) {
                const path = loadedPaths[pathIndex];
                if (path.floor !== currentFloor) continue;
                if (!path.edges || !path.vertices) continue;

                for (let edge of path.edges) {
                    const fromVertex = path.vertices.find(v => v.id === edge.from);
                    const toVertex = path.vertices.find(v => v.id === edge.to);
                    if (!fromVertex || !toVertex) continue;

                    const p1Map = worldToPixel(fromVertex.x, fromVertex.y);
                    const p2Map = worldToPixel(toVertex.x, toVertex.y);
                    const p1 = mapToScreen(p1Map.x, p1Map.y);
                    const p2 = mapToScreen(p2Map.x, p2Map.y);

                    const dist = distanceToSegment(pixelPos, p1, p2);
                    if (dist < 8) {
                        return { type: 'edge', element: edge, source: 'loaded', pathIndex: pathIndex };
                    }
                }
            }

            return null;
        }


        function distanceToSegment(p, a, b) {
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const l2 = dx * dx + dy * dy;
            if (l2 === 0) return distance(p, a);

            let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2;
            t = Math.max(0, Math.min(1, t));

            const projection = {
                x: a.x + t * dx,
                y: a.y + t * dy
            };

            return distance(p, projection);
        }


        function findNearestEdge(pixelPos, maxDistance = 30) {
            const currentFloor = mapData[currentMap].floor;
            let nearestEdge = null;
            let nearestDistance = Infinity;
            let nearestPathIndex = -1;
            let nearestPath = null;


            for (let pathIndex = 0; pathIndex < loadedPaths.length; pathIndex++) {
                const path = loadedPaths[pathIndex];
                if (path.floor !== currentFloor) continue;
                if (!path.edges || !path.vertices) continue;

                for (let edge of path.edges) {
                    const fromVertex = path.vertices.find(v => v.id === edge.from);
                    const toVertex = path.vertices.find(v => v.id === edge.to);
                    if (!fromVertex || !toVertex) continue;

                    const p1Map = worldToPixel(fromVertex.x, fromVertex.y);
                    const p2Map = worldToPixel(toVertex.x, toVertex.y);
                    const p1 = mapToScreen(p1Map.x, p1Map.y);
                    const p2 = mapToScreen(p2Map.x, p2Map.y);

                    const dist = distanceToSegment(pixelPos, p1, p2);
                    if (dist < maxDistance && dist < nearestDistance) {
                        nearestDistance = dist;
                        nearestEdge = edge;
                        nearestPathIndex = pathIndex;
                        nearestPath = path;
                    }
                }
            }


            for (let edge of edges) {
                const fromVertex = vertices.find(v => v.id === edge.from);
                const toVertex = vertices.find(v => v.id === edge.to);
                if (!fromVertex || !toVertex) continue;
                if (fromVertex.z !== currentFloor) continue;

                const p1Map = worldToPixel(fromVertex.x, fromVertex.y);
                const p2Map = worldToPixel(toVertex.x, toVertex.y);
                const p1 = mapToScreen(p1Map.x, p1Map.y);
                const p2 = mapToScreen(p2Map.x, p2Map.y);

                const dist = distanceToSegment(pixelPos, p1, p2);
                if (dist < maxDistance && dist < nearestDistance) {
                    nearestDistance = dist;
                    nearestEdge = edge;
                    nearestPathIndex = -1;
                    nearestPath = null;
                }
            }

            return nearestEdge ? {
                edge: nearestEdge,
                pathIndex: nearestPathIndex,
                path: nearestPath,
                distance: nearestDistance
            } : null;
        }


        function getVertexDegree(vertexId) {
            let degree = 0;


            for (let edge of edges) {
                if (edge.from === vertexId) degree++;
                if (edge.to === vertexId) degree++;
            }


            for (let path of loadedPaths) {
                if (!path.edges) continue;
                for (let edge of path.edges) {
                    if (edge.from === vertexId) degree++;
                    if (edge.to === vertexId) degree++;
                }
            }

            return degree;
        }


        function getVertexColor(degree) {
            if (degree <= 2) return '#808080';
            if (degree === 3) return '#FF0000';
            if (degree === 4) return '#FF7F00';
            if (degree === 5) return '#FFFF00';
            if (degree === 6) return '#00FF00';
            if (degree === 7) return '#0000FF';
            if (degree === 8) return '#4B0082';
            return '#9400D3';
        }

        function rebuildVertexMap() {
            vertexMap = {};
            if (loadedPaths) {
                loadedPaths.forEach(path => {
                    if (path.vertices) {
                        path.vertices.forEach(v => {
                            vertexMap[v.id] = v;
                        });
                    }
                });
            }
            // Include current editing vertices if any
            if (vertices) {
                vertices.forEach(v => {
                    vertexMap[v.id] = v;
                });
            }
        }

        function drawAgvPaths() {
            if (!simRunning) return;

            agvs.forEach(agv => {
                if (!agv.assignedPath || agv.assignedPath.length === 0) return;
                if (agv.status !== 'working') return;


                const agvBaseColor = getAgvDisplayColor(agv);


                const currentEdgeIdx = agv.sim_state?.edge_idx ?? agv.simState?.edgeIdx ?? 0;

                ctx.lineWidth = 3;
                ctx.setLineDash([5, 5]); // Dashed line


                for (let index = currentEdgeIdx; index < agv.assignedPath.length; index++) {
                    const edge = agv.assignedPath[index];

                    const fromV = vertexMap[edge.source];
                    const toV = vertexMap[edge.target];

                    if (fromV && toV) {
                        const p1 = worldToPixel(fromV.x, fromV.y);
                        const p2 = worldToPixel(toV.x, toV.y);


                        const isReleased = edge.released === true;
                        const edgeColor = isReleased ? agvBaseColor : adjustColorBrightness(agvBaseColor, 0.5);

                        ctx.strokeStyle = edgeColor;
                        ctx.beginPath();

                        if (index === currentEdgeIdx && agv.position) {

                            const pAgv = worldToPixel(agv.position.x, agv.position.y);
                            ctx.moveTo(pAgv.x, pAgv.y);
                            ctx.lineTo(p2.x, p2.y);
                        } else {
                            ctx.moveTo(p1.x, p1.y);
                            ctx.lineTo(p2.x, p2.y);
                        }

                        ctx.stroke();
                    } else {
                        // Debug: log missing vertices (only once per AGV to avoid spam)
                        if (index === currentEdgeIdx) {
                            if (!fromV) console.warn(`Vertex not found: ${edge.source} for AGV ${agv.id || agv.name}`);
                            if (!toV) console.warn(`Vertex not found: ${edge.target} for AGV ${agv.id || agv.name}`);
                        }
                    }
                }

                ctx.setLineDash([]); // Reset dash
            });
        }



        function redraw() {
            if (!mapImage) return;

            // Ensure vertex map is up to date
            rebuildVertexMap();

            // Clear with identity transform
            ctx.save();
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.restore();

            // Apply View Transform
            ctx.save();
            ctx.translate(viewPan.x, viewPan.y);
            ctx.scale(viewScale, viewScale);

            ctx.drawImage(mapImage, 0, 0);

            const currentFloor = mapData[currentMap].floor;


            if (showGrid) {
                drawGrid(currentFloor);
            }


            drawLoadedPaths(currentFloor);


            drawAgvPaths();


            drawEdges(currentFloor);


            drawVertices(currentFloor);


            if (currentMode === 'path' && currentMousePos) {

                let snapTarget = null;
                if (snapEnabled) {
                    snapTarget = findNearbyVertexForSnap(currentMousePos, snapRadius);
                }


                if (snapTarget) {
                    const snapPixel = worldToPixel(snapTarget.x, snapTarget.y);
                    ctx.strokeStyle = '#00FF00';
                    ctx.lineWidth = 3 / viewScale;
                    ctx.setLineDash([3 / viewScale, 3 / viewScale]);
                    ctx.beginPath();
                    ctx.arc(snapPixel.x, snapPixel.y, 15 / viewScale, 0, Math.PI * 2);
                    ctx.stroke();
                    ctx.setLineDash([]);


                    if (lastVertex && lastVertex.id !== snapTarget.id) {
                        const lastPixel = worldToPixel(lastVertex.x, lastVertex.y);
                        ctx.strokeStyle = 'rgba(0, 255, 0, 0.6)';
                        ctx.lineWidth = 2 / viewScale;
                        ctx.setLineDash([5 / viewScale, 5 / viewScale]);
                        ctx.beginPath();
                        ctx.moveTo(lastPixel.x, lastPixel.y);
                        ctx.lineTo(snapPixel.x, snapPixel.y);
                        ctx.stroke();
                        ctx.setLineDash([]);
                    }
                } else if (lastVertex) {

                    const lastPixel = worldToPixel(lastVertex.x, lastVertex.y);
                    const mouseMap = screenToMap(currentMousePos.x, currentMousePos.y);

                    ctx.strokeStyle = 'rgba(135, 206, 250, 0.6)';
                    ctx.lineWidth = 2 / viewScale;
                    ctx.setLineDash([5 / viewScale, 5 / viewScale]);
                    ctx.beginPath();
                    ctx.moveTo(lastPixel.x, lastPixel.y);
                    ctx.lineTo(mouseMap.x, mouseMap.y);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
            }


            drawAgvs(currentFloor);


            drawMeasurementOverlay(currentFloor);


            drawTaskVertexHighlight();


            if (selectedElement) {
                drawSelectedHighlight(selectedElement);
            }


            if (hoveredElement && hoveredElement !== selectedElement) {
                drawHoverHighlight(hoveredElement);
            }


            if (currentMode === 'edit' && editOperation === 'insert' && hoveredEdge) {
                drawHoveredEdge(hoveredEdge);
            }

            ctx.restore();
        }

        function drawHoveredEdge(nearestEdgeInfo) {
            const edge = nearestEdgeInfo.edge;
            let fromVertex, toVertex;

            if (nearestEdgeInfo.path) {
                fromVertex = nearestEdgeInfo.path.vertices.find(v => v.id === edge.from);
                toVertex = nearestEdgeInfo.path.vertices.find(v => v.id === edge.to);
            } else {
                fromVertex = vertices.find(v => v.id === edge.from);
                toVertex = vertices.find(v => v.id === edge.to);
            }

            if (fromVertex && toVertex) {
                const p1 = worldToPixel(fromVertex.x, fromVertex.y);
                const p2 = worldToPixel(toVertex.x, toVertex.y);

                ctx.strokeStyle = '#FF00FF';
                ctx.lineWidth = 4 / viewScale;
                ctx.setLineDash([5 / viewScale, 5 / viewScale]);
                ctx.globalAlpha = 0.8;
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.globalAlpha = 1.0;
            }
        }

        function drawVertices(currentFloor) {
            vertices.forEach(vertex => {
                if (vertex.z !== currentFloor) return;

                const p = worldToPixel(vertex.x, vertex.y);
                const degree = getVertexDegree(vertex.id);
                const color = getVertexColor(degree);


                const rgbaColor = colorToRgba(color, 0.6);


                ctx.fillStyle = rgbaColor;
                ctx.beginPath();


                const isChargeStation = vertex.type === 'charging_station';
                const isStandbyPoint = vertex.type === 'standby_point';
                if (isChargeStation) {

                    const size = 16 / viewScale;
                    ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
                } else if (isStandbyPoint) {

                    const size = 16 / viewScale;
                    ctx.moveTo(p.x, p.y - size / 2);
                    ctx.lineTo(p.x - size / 2, p.y + size / 2);
                    ctx.lineTo(p.x + size / 2, p.y + size / 2);
                    ctx.closePath();
                    ctx.fill();
                } else {

                    ctx.arc(p.x, p.y, 8 / viewScale, 0, Math.PI * 2);
                    ctx.fill();
                }

                ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
                ctx.lineWidth = 2 / viewScale;
                if (isChargeStation) {

                    const size = 16 / viewScale;
                    ctx.strokeRect(p.x - size / 2, p.y - size / 2, size, size);
                } else if (isStandbyPoint) {

                    const size = 16 / viewScale;
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y - size / 2);
                    ctx.lineTo(p.x - size / 2, p.y + size / 2);
                    ctx.lineTo(p.x + size / 2, p.y + size / 2);
                    ctx.closePath();
                    ctx.stroke();
                } else {
                    ctx.stroke();
                }


                if (vertex.id) {
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
                    ctx.font = `bold ${10 / viewScale}px Arial`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(vertex.id.substring(0, 4), p.x, p.y);
                }


                if (vertex.type && vertex.type !== 'waypoint') {
                    ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
                    ctx.font = `${12 / viewScale}px Arial`;
                    ctx.textAlign = 'center';
                    let icon = 'o';
                    if (vertex.type === 'work_station') icon = 'PKG';
                    else if (vertex.type === 'elevator_entrance') icon = 'LIFT';
                    else if (vertex.type === 'charging_station') icon = 'BAT';
                    else if (vertex.type === 'standby_point') icon = 'WAIT';
                    ctx.fillText(icon, p.x, p.y - 15 / viewScale);
                }
            });
        }


        function adjustColorBrightness(color, factor) {

            if (!color) return color;


            if (color.startsWith('#')) {
                let r, g, b;
                if (color.length === 4) {
                    r = parseInt(color[1] + color[1], 16);
                    g = parseInt(color[2] + color[2], 16);
                    b = parseInt(color[3] + color[3], 16);
                } else {
                    r = parseInt(color.substr(1, 2), 16);
                    g = parseInt(color.substr(3, 2), 16);
                    b = parseInt(color.substr(5, 2), 16);
                }

                r = Math.round(r + (255 - r) * (1 - factor));
                g = Math.round(g + (255 - g) * (1 - factor));
                b = Math.round(b + (255 - b) * (1 - factor));
                return `rgb(${r}, ${g}, ${b})`;
            }


            if (color.startsWith('rgb')) {
                const match = color.match(/\d+/g);
                if (match && match.length >= 3) {
                    let r = parseInt(match[0]);
                    let g = parseInt(match[1]);
                    let b = parseInt(match[2]);
                    r = Math.round(r + (255 - r) * (1 - factor));
                    g = Math.round(g + (255 - g) * (1 - factor));
                    b = Math.round(b + (255 - b) * (1 - factor));
                    if (color.startsWith('rgba')) {
                        const alpha = match[3] || '1';
                        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                    }
                    return `rgb(${r}, ${g}, ${b})`;
                }
            }

            return color;
        }

        function drawGrid(currentFloor) {



            if (!currentMap || !mapData[currentMap]) return;

            const data = mapData[currentMap];
            const resolution = data.resolution;



            const topLeftWorld = pixelToWorld(0, 0);
            const bottomRightWorld = pixelToWorld(canvas.width, canvas.height);


            const minX = Math.min(topLeftWorld.x, bottomRightWorld.x);
            const maxX = Math.max(topLeftWorld.x, bottomRightWorld.x);
            const minY = Math.min(topLeftWorld.y, bottomRightWorld.y);
            const maxY = Math.max(topLeftWorld.y, bottomRightWorld.y);


            const expandedMinX = minX - gridSize;
            const expandedMaxX = maxX + gridSize;
            const expandedMinY = minY - gridSize;
            const expandedMaxY = maxY + gridSize;


            const startX = Math.floor(expandedMinX / gridSize) * gridSize;
            const endX = Math.ceil(expandedMaxX / gridSize) * gridSize;
            const startY = Math.floor(expandedMinY / gridSize) * gridSize;
            const endY = Math.ceil(expandedMaxY / gridSize) * gridSize;


            ctx.strokeStyle = 'rgba(200, 200, 200, 0.4)';


            ctx.lineWidth = viewScale < 1 ? (1 / viewScale) : 0.5;
            ctx.setLineDash([]);


            for (let x = startX; x <= endX; x += gridSize) {
                const p1 = worldToPixel(x, startY);
                const p2 = worldToPixel(x, endY);
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
            }


            for (let y = startY; y <= endY; y += gridSize) {
                const p1 = worldToPixel(startX, y);
                const p2 = worldToPixel(endX, y);
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
            }
        }

        function colorToRgba(color, alpha) {
            if (!color) return `rgba(128, 128, 128, ${alpha})`;

            if (color.startsWith('rgba')) {
                return color.replace(/,\s*[\d.]+\)$/, `, ${alpha})`);
            }

            if (color.startsWith('rgb')) {
                return color.replace('rgb', 'rgba').replace(')', `, ${alpha})`);
            }

            if (color.startsWith('#')) {
                let r, g, b;
                if (color.length === 4) {

                    r = parseInt(color[1] + color[1], 16);
                    g = parseInt(color[2] + color[2], 16);
                    b = parseInt(color[3] + color[3], 16);
                } else {

                    r = parseInt(color.slice(1, 3), 16);
                    g = parseInt(color.slice(3, 5), 16);
                    b = parseInt(color.slice(5, 7), 16);
                }
                return `rgba(${r}, ${g}, ${b}, ${alpha})`;
            }

            return `rgba(128, 128, 128, ${alpha})`;
        }

        function drawEdges(currentFloor) {
            const resolution = mapData[currentMap].resolution;
            edges.forEach(edge => {
                const fromVertex = vertices.find(v => v.id === edge.from);
                const toVertex = vertices.find(v => v.id === edge.to);
                if (!fromVertex || !toVertex) return;
                if (fromVertex.z !== currentFloor) return;

                const p1 = worldToPixel(fromVertex.x, fromVertex.y);
                const p2 = worldToPixel(toVertex.x, toVertex.y);


                const edgeWidth = edge.width || 0.6;
                const lineWidthPixels = edgeWidth / resolution;


                const edgeColor = edge.direction === 'bidirectional' ? EDGE_COLOR_DOUBLE : EDGE_COLOR_SINGLE;
                ctx.strokeStyle = edgeColor;
                ctx.lineWidth = lineWidthPixels;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();


                drawArrow(p1, p2, edge.direction);


                if (edge.id) {
                    const midX = (p1.x + p2.x) / 2;
                    const midY = (p1.y + p2.y) / 2;
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
                    ctx.strokeStyle = 'rgba(0, 0, 0, 0.8)';
                    ctx.lineWidth = 2;
                    ctx.font = 'bold 11px Arial';
                    ctx.textAlign = 'center';
                    ctx.strokeText(edge.id.substring(0, 4), midX, midY);
                    ctx.fillText(edge.id.substring(0, 4), midX, midY);
                }
            });
        }

        function drawArrow(from, to, direction) {
            const angle = Math.atan2(to.y - from.y, to.x - from.x);
            const arrowSize = 10;


            if (direction === 'unidirectional') {
                const tipX = to.x - 15 * Math.cos(angle);
                const tipY = to.y - 15 * Math.sin(angle);

                ctx.fillStyle = EDGE_ARROW_COLOR_SINGLE;
                ctx.beginPath();
                ctx.moveTo(tipX, tipY);
                ctx.lineTo(
                    tipX - arrowSize * Math.cos(angle - Math.PI / 6),
                    tipY - arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tipX - arrowSize * Math.cos(angle + Math.PI / 6),
                    tipY - arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();
            }

            else if (direction === 'bidirectional') {

                const tip1X = to.x - 15 * Math.cos(angle);
                const tip1Y = to.y - 15 * Math.sin(angle);

                ctx.fillStyle = EDGE_ARROW_COLOR_DOUBLE;
                ctx.beginPath();
                ctx.moveTo(tip1X, tip1Y);
                ctx.lineTo(
                    tip1X - arrowSize * Math.cos(angle - Math.PI / 6),
                    tip1Y - arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tip1X - arrowSize * Math.cos(angle + Math.PI / 6),
                    tip1Y - arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();


                const tip2X = from.x + 15 * Math.cos(angle);
                const tip2Y = from.y + 15 * Math.sin(angle);

                ctx.beginPath();
                ctx.moveTo(tip2X, tip2Y);
                ctx.lineTo(
                    tip2X + arrowSize * Math.cos(angle - Math.PI / 6),
                    tip2Y + arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tip2X + arrowSize * Math.cos(angle + Math.PI / 6),
                    tip2Y + arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();
            }
        }

        function rebuildVertexMap() {
            vertexMap = {};
            if (loadedPaths) {
                loadedPaths.forEach(path => {
                    if (path.vertices) {
                        path.vertices.forEach(v => {
                            vertexMap[v.id] = v;
                        });
                    }
                });
            }
            // Include current editing vertices if any
            if (vertices) {
                vertices.forEach(v => {
                    vertexMap[v.id] = v;
                });
            }
        }

        function drawAgvPaths() {
            if (!simRunning) return;

            agvs.forEach(agv => {
                if (!agv.assignedPath || agv.assignedPath.length === 0) return;
                if (agv.status !== 'working') return;


                const agvBaseColor = getAgvDisplayColor(agv);


                const currentEdgeIdx = agv.sim_state?.edge_idx ?? agv.simState?.edgeIdx ?? 0;

                ctx.lineWidth = 3;
                ctx.setLineDash([5, 5]); // Dashed line


                for (let index = currentEdgeIdx; index < agv.assignedPath.length; index++) {
                    const edge = agv.assignedPath[index];

                    const fromV = vertexMap[edge.source];
                    const toV = vertexMap[edge.target];

                    if (fromV && toV) {
                        const p1 = worldToPixel(fromV.x, fromV.y);
                        const p2 = worldToPixel(toV.x, toV.y);


                        const isReleased = edge.released === true;
                        const edgeColor = isReleased ? agvBaseColor : adjustColorBrightness(agvBaseColor, 0.5);

                        ctx.strokeStyle = edgeColor;
                        ctx.beginPath();

                        if (index === currentEdgeIdx && agv.position) {

                            const pAgv = worldToPixel(agv.position.x, agv.position.y);
                            ctx.moveTo(pAgv.x, pAgv.y);
                            ctx.lineTo(p2.x, p2.y);
                        } else {
                            ctx.moveTo(p1.x, p1.y);
                            ctx.lineTo(p2.x, p2.y);
                        }

                        ctx.stroke();
                    } else {
                        // Debug: log missing vertices (only once per AGV to avoid spam)
                        if (index === currentEdgeIdx) {
                            if (!fromV) console.warn(`Vertex not found: ${edge.source} for AGV ${agv.id || agv.name}`);
                            if (!toV) console.warn(`Vertex not found: ${edge.target} for AGV ${agv.id || agv.name}`);
                        }
                    }
                }

                ctx.setLineDash([]); // Reset dash
            });
        }

        function drawLoadedPaths(currentFloor) {
            // Ensure vertex map is up to date
            rebuildVertexMap();

            const resolution = mapData[currentMap].resolution;
            loadedPaths.forEach((path, index) => {
                if (path.floor !== currentFloor) return;


                if (path.edges) {
                    path.edges.forEach(edge => {
                        const fromV = path.vertices.find(v => v.id === edge.from);
                        const toV = path.vertices.find(v => v.id === edge.to);
                        if (!fromV || !toV) return;

                        const p1 = worldToPixel(fromV.x, fromV.y);
                        const p2 = worldToPixel(toV.x, toV.y);


                        const edgeWidth = edge.width || 0.6;
                        const lineWidthPixels = edgeWidth / resolution;


                        const edgeColor = (edge.direction || 'bidirectional') === 'bidirectional'
                            ? EDGE_COLOR_DOUBLE
                            : EDGE_COLOR_SINGLE;


                        ctx.strokeStyle = edgeColor;
                        ctx.lineWidth = lineWidthPixels;
                        ctx.lineCap = 'round';
                        ctx.beginPath();
                        ctx.moveTo(p1.x, p1.y);
                        ctx.lineTo(p2.x, p2.y);
                        ctx.stroke();


                        drawArrowForLoadedPath(p1, p2, edge.direction || 'bidirectional');
                    });
                }


                if (path.vertices) {
                    path.vertices.forEach(vertex => {
                        const p = worldToPixel(vertex.x, vertex.y);


                        const degree = getVertexDegree(vertex.id);
                        const color = getVertexColor(degree);
                        const rgbaColor = colorToRgba(color, 0.6);

                        ctx.fillStyle = rgbaColor;
                        ctx.beginPath();


                        const isChargeStation = vertex.type === 'charging_station';
                        const isStandbyPoint = vertex.type === 'standby_point';
                        if (isChargeStation) {

                            const size = 16;
                            ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
                        } else if (isStandbyPoint) {

                            const size = 16;
                            ctx.moveTo(p.x, p.y - size / 2);
                            ctx.lineTo(p.x - size / 2, p.y + size / 2);
                            ctx.lineTo(p.x + size / 2, p.y + size / 2);
                            ctx.closePath();
                            ctx.fill();
                        } else {

                            ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
                            ctx.fill();
                        }


                        ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
                        ctx.lineWidth = 2;
                        if (isChargeStation) {

                            ctx.strokeRect(p.x - 16 / 2, p.y - 16 / 2, 14, 14);
                        } else if (isStandbyPoint) {

                            ctx.beginPath();
                            ctx.moveTo(p.x, p.y - 16 / 2);
                            ctx.lineTo(p.x - 16 / 2, p.y + 16 / 2);
                            ctx.lineTo(p.x + 16 / 2, p.y + 16 / 2);
                            ctx.closePath();
                            ctx.stroke();
                        } else {
                            ctx.stroke();
                        }
                    });
                }
            });
        }

        function drawArrowForLoadedPath(from, to, direction) {
            const angle = Math.atan2(to.y - from.y, to.x - from.x);
            const arrowSize = 8;
            const arrowColor = (direction === 'bidirectional') ? EDGE_ARROW_COLOR_DOUBLE : EDGE_ARROW_COLOR_SINGLE;


            if (direction === 'unidirectional') {
                const tipX = to.x - 12 * Math.cos(angle);
                const tipY = to.y - 12 * Math.sin(angle);

                ctx.fillStyle = EDGE_ARROW_COLOR_SINGLE;
                ctx.beginPath();
                ctx.moveTo(tipX, tipY);
                ctx.lineTo(
                    tipX - arrowSize * Math.cos(angle - Math.PI / 6),
                    tipY - arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tipX - arrowSize * Math.cos(angle + Math.PI / 6),
                    tipY - arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();
            }

            else if (direction === 'bidirectional') {

                const tip1X = to.x - 12 * Math.cos(angle);
                const tip1Y = to.y - 12 * Math.sin(angle);

                ctx.fillStyle = EDGE_ARROW_COLOR_DOUBLE;
                ctx.beginPath();
                ctx.moveTo(tip1X, tip1Y);
                ctx.lineTo(
                    tip1X - arrowSize * Math.cos(angle - Math.PI / 6),
                    tip1Y - arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tip1X - arrowSize * Math.cos(angle + Math.PI / 6),
                    tip1Y - arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();


                const tip2X = from.x + 12 * Math.cos(angle);
                const tip2Y = from.y + 12 * Math.sin(angle);

                ctx.beginPath();
                ctx.moveTo(tip2X, tip2Y);
                ctx.lineTo(
                    tip2X + arrowSize * Math.cos(angle - Math.PI / 6),
                    tip2Y + arrowSize * Math.sin(angle - Math.PI / 6)
                );
                ctx.lineTo(
                    tip2X + arrowSize * Math.cos(angle + Math.PI / 6),
                    tip2Y + arrowSize * Math.sin(angle + Math.PI / 6)
                );
                ctx.closePath();
                ctx.fill();
            }
        }

        function getAgvDimensions(agv) {
            const length = agv.length || agv.dimensions?.length || 0.7;
            const width = agv.width || agv.dimensions?.width || 0.5;
            return { length, width };
        }

        function getAgvMaxSpeed(agv) {
            if (!agv) return 1.0;
            const value = parseFloat(agv.max_speed);
            return Number.isFinite(value) && value > 0 ? value : 1.0;
        }


        function drawAgvs(currentFloor) {
            const resolution = mapData[currentMap].resolution;
            const outlineColorMap = {
                moving: '#28a745',
                idle: '#6c757d',
                charging: '#ffc107',
                error: '#dc3545'
            };

            agvs.forEach(agv => {
                if (agv.position.z !== currentFloor) return;

                const p = worldToPixel(agv.position.x, agv.position.y);
                const dirAngle = agv.orientation || 0;
                const { length, width } = getAgvDimensions(agv);
                const halfLength = (length / resolution) / 2;
                const halfWidth = (width / resolution) / 2;

                const bodyColor = getAgvDisplayColor(agv);
                const statusKey = normalizeStatusClass(agv.status);
                const outlineColorBase = outlineColorMap[statusKey] || '#FFFFFF';
                const strokeColor = agv.id === selectedAgvId ? '#FFD700' : outlineColorBase;

                const corners = [
                    { x: -halfLength, y: -halfWidth },
                    { x: halfLength, y: -halfWidth },
                    { x: halfLength, y: halfWidth },
                    { x: -halfLength, y: halfWidth }
                ].map(point => {
                    return {
                        x: p.x + point.x * Math.cos(dirAngle) - point.y * Math.sin(dirAngle),
                        y: p.y - (point.x * Math.sin(dirAngle) + point.y * Math.cos(dirAngle))
                    };
                });

                ctx.save();
                ctx.fillStyle = bodyColor;
                ctx.strokeStyle = strokeColor;
                ctx.lineWidth = agv.id === selectedAgvId ? 3 : 2;
                ctx.beginPath();
                ctx.moveTo(corners[0].x, corners[0].y);
                corners.forEach(corner => ctx.lineTo(corner.x, corner.y));
                ctx.closePath();
                ctx.fill();
                ctx.stroke();


                const noseLength = halfLength;
                const noseX = p.x + noseLength * Math.cos(dirAngle);
                const noseY = p.y - noseLength * Math.sin(dirAngle);
                ctx.strokeStyle = '#FFFFFF';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.moveTo(p.x, p.y);
                ctx.lineTo(noseX, noseY);
                ctx.stroke();
                ctx.restore();


                const label = agv.name || (agv.id ? agv.id.substring(0, 6) : 'AGV');
                ctx.save();
                ctx.font = 'bold 13px "SF Pro Display", Arial, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'bottom';
                const metrics = ctx.measureText(label);
                const boxWidth = metrics.width + 14;
                const boxHeight = 20;
                const labelBottom = p.y - halfWidth - 6;
                ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
                ctx.fillRect(p.x - boxWidth / 2, labelBottom - boxHeight, boxWidth, boxHeight);
                ctx.lineWidth = 3;
                ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
                ctx.strokeText(label, p.x, labelBottom - 4);
                ctx.fillStyle = '#FFFFFF';
                ctx.fillText(label, p.x, labelBottom - 4);
                ctx.restore();
            });
        }

        function findAgvAtPixel(pixelPos) {
            const resolution = mapData[currentMap].resolution;
            for (let i = agvs.length - 1; i >= 0; i--) {
                const agv = agvs[i];
                if (!agv.position) continue;
                if (mapData[currentMap].floor !== agv.position.z) continue;

                const centerMap = worldToPixel(agv.position.x, agv.position.y);
                const center = mapToScreen(centerMap.x, centerMap.y);

                const angle = agv.orientation || 0;
                const { length, width } = getAgvDimensions(agv);

                // Convert dimensions to screen pixels
                const halfL = ((length / resolution) / 2) * viewScale;
                const halfW = ((width / resolution) / 2) * viewScale;

                const dx = pixelPos.x - center.x;
                const dy = pixelPos.y - center.y;
                const localX = dx * Math.cos(angle) - dy * Math.sin(angle);
                const localY = dx * Math.sin(angle) + dy * Math.cos(angle);
                if (Math.abs(localX) <= halfL && Math.abs(localY) <= halfW) {
                    return agv;
                }
            }
            return null;
        }

        function drawMeasurementOverlay(currentFloor) {
            if (measurePoints.length === 0) {
                return;
            }

            ctx.save();
            ctx.strokeStyle = '#FFD700';
            ctx.fillStyle = '#FFD700';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            const visiblePoints = measurePoints.filter(point => point.z === currentFloor);
            if (visiblePoints.length === 0) {
                ctx.restore();
                return;
            }

            const visiblePixels = visiblePoints.map(point => {
                const pixel = worldToPixel(point.x, point.y);
                ctx.beginPath();
                ctx.arc(pixel.x, pixel.y, 6, 0, Math.PI * 2);
                ctx.fill();
                return pixel;
            });

            let displayDistance = null;
            let startPixel = visiblePixels[0];
            let endPixel = null;

            if (measurePoints.length === 2 && measurePoints.every(point => point.z === currentFloor)) {
                const p1 = visiblePixels[0];
                const p2 = visiblePixels[1];
                if (p1 && p2) {
                    ctx.beginPath();
                    ctx.moveTo(p1.x, p1.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.stroke();
                    displayDistance = worldDistance(measurePoints[0], measurePoints[1]);
                    endPixel = p2;
                }
            } else if (measurePoints.length === 1 && currentMode === 'measure' && currentMousePos && measurePoints[0].z === currentFloor) {
                const previewWorld = pixelToWorld(currentMousePos.x, currentMousePos.y);
                if (previewWorld.z === currentFloor) {
                    const mouseMap = screenToMap(currentMousePos.x, currentMousePos.y);
                    const previewPixel = mouseMap;
                    const p1 = visiblePixels[0];
                    if (p1) {
                        ctx.beginPath();
                        ctx.moveTo(p1.x, p1.y);
                        ctx.lineTo(previewPixel.x, previewPixel.y);
                        ctx.stroke();
                        displayDistance = worldDistance(measurePoints[0], previewWorld);
                        endPixel = previewPixel;
                    }
                }
            }

            if (displayDistance !== null && startPixel && endPixel) {
                ctx.setLineDash([]);
                const midX = (startPixel.x + endPixel.x) / 2;
                const midY = (startPixel.y + endPixel.y) / 2;
                const text = `${displayDistance.toFixed(2)} m`;
                const padding = 6;
                ctx.font = 'bold 14px Arial';
                const textWidth = ctx.measureText(text).width;
                ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
                ctx.fillRect(midX - textWidth / 2 - padding, midY - 24, textWidth + padding * 2, 20);
                ctx.fillStyle = '#FFD700';
                ctx.fillText(text, midX, midY - 14);
            }

            ctx.restore();
        }

        function handleMeasurementClick(worldPos) {
            if (measurePoints.length === 0) {
                measurePoints.push(worldPos);
                updateInfo('Start point set; click to set the end point');
            } else if (measurePoints.length === 1) {
                if (worldPos.z !== measurePoints[0].z) {
                    updateInfo('Select points on the same floor');
                    return;
                }
                measurePoints.push(worldPos);
                const dist = worldDistance(measurePoints[0], measurePoints[1]);
                updateInfo(`Measured distance: ${dist.toFixed(3)} m`);
            } else {
                measurePoints = [worldPos];
                updateInfo('Measurement reset; click to set the end point');
            }
            redraw();
        }

        function clearMeasurement() {
            measurePoints = [];
        }


        function findVertexById(vertexId) {
            if (!vertexId) return null;

            if (vertexMap[vertexId]) return vertexMap[vertexId];

            const v = vertices.find(v => v.id === vertexId);
            if (v) return v;

            for (let path of loadedPaths) {
                if (path.vertices) {
                    const found = path.vertices.find(v => v.id === vertexId);
                    if (found) return found;
                }
            }
            return null;
        }


        function drawTaskVertexHighlight() {
            const hasStart = highlightedTaskVertices.start;
            const hasEndVertices = highlightedTaskVertices.end_vertices && highlightedTaskVertices.end_vertices.length > 0;
            const hasEnd = highlightedTaskVertices.end;
            if (!hasStart && !hasEndVertices && !hasEnd) return;

            const currentFloor = mapData[currentMap].floor;


            if (highlightedTaskVertices.start) {
                const startVertex = findVertexById(highlightedTaskVertices.start);
                if (startVertex && startVertex.z === currentFloor) {
                    const p = worldToPixel(startVertex.x, startVertex.y);

                    ctx.strokeStyle = '#28a745';
                    ctx.lineWidth = 4 / viewScale;
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 14 / viewScale, 0, Math.PI * 2);
                    ctx.stroke();

                    ctx.strokeStyle = '#28a745';
                    ctx.lineWidth = 2 / viewScale;
                    ctx.globalAlpha = 0.5;
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 18 / viewScale, 0, Math.PI * 2);
                    ctx.stroke();
                    ctx.globalAlpha = 1.0;
                }
            }


            const endVertices = highlightedTaskVertices.end_vertices || (highlightedTaskVertices.end ? [highlightedTaskVertices.end] : []);
            if (endVertices.length > 0) {
                endVertices.forEach((endVertexId, index) => {
                    const endVertex = findVertexById(endVertexId);
                    if (endVertex && endVertex.z === currentFloor) {
                        const p = worldToPixel(endVertex.x, endVertex.y);

                        ctx.strokeStyle = '#dc3545';
                        ctx.lineWidth = 4 / viewScale;
                        ctx.beginPath();
                        ctx.arc(p.x, p.y, 14 / viewScale, 0, Math.PI * 2);
                        ctx.stroke();

                        ctx.strokeStyle = '#dc3545';
                        ctx.lineWidth = 2 / viewScale;
                        ctx.globalAlpha = 0.5;
                        ctx.beginPath();
                        ctx.arc(p.x, p.y, 18 / viewScale, 0, Math.PI * 2);
                        ctx.stroke();
                        ctx.globalAlpha = 1.0;


                        const fontSize = 12 / viewScale;
                        const superscriptOffset = 4 / viewScale;
                        ctx.fillStyle = '#dc3545';
                        ctx.font = `bold ${fontSize}px Arial`;
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'bottom';

                        ctx.fillText(`${index + 1}`, p.x, p.y - 18 / viewScale - superscriptOffset);
                    }
                });
            }
        }

        function drawSelectedHighlight(element) {
            if (element.type === 'vertex') {
                const p = worldToPixel(element.element.x, element.element.y);
                ctx.strokeStyle = '#FFD700';
                ctx.lineWidth = 3 / viewScale;
                ctx.beginPath();
                ctx.arc(p.x, p.y, 12 / viewScale, 0, Math.PI * 2);
                ctx.stroke();
            } else if (element.type === 'edge') {

                let fromV, toV;
                if (element.source === 'loaded') {
                    const path = loadedPaths[element.pathIndex];
                    fromV = path.vertices.find(v => v.id === element.element.from);
                    toV = path.vertices.find(v => v.id === element.element.to);
                } else {
                    fromV = vertices.find(v => v.id === element.element.from);
                    toV = vertices.find(v => v.id === element.element.to);
                }

                if (fromV && toV) {
                    const p1 = worldToPixel(fromV.x, fromV.y);
                    const p2 = worldToPixel(toV.x, toV.y);
                    ctx.strokeStyle = '#FFD700';
                    ctx.lineWidth = 5 / viewScale;
                    ctx.globalAlpha = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(p1.x, p1.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.stroke();
                    ctx.globalAlpha = 1.0;
                }
            }
        }

        function drawHoverHighlight(element) {

            if (hoveredPath) {
                const currentFloor = mapData[currentMap].floor;
                if (hoveredPath.floor === currentFloor) {

                    if (hoveredPath.edges && hoveredPath.vertices) {
                        ctx.strokeStyle = '#00FFFF';
                        ctx.lineWidth = 5;
                        ctx.globalAlpha = 0.7;

                        hoveredPath.edges.forEach(edge => {
                            const fromV = hoveredPath.vertices.find(v => v.id === edge.from);
                            const toV = hoveredPath.vertices.find(v => v.id === edge.to);
                            if (fromV && toV) {
                                const p1 = worldToPixel(fromV.x, fromV.y);
                                const p2 = worldToPixel(toV.x, toV.y);
                                ctx.beginPath();
                                ctx.moveTo(p1.x, p1.y);
                                ctx.lineTo(p2.x, p2.y);
                                ctx.stroke();
                            }
                        });

                        ctx.globalAlpha = 1.0;
                    }


                    if (hoveredPath.name && currentMousePos) {
                        const mouseX = currentMousePos.x;
                        const mouseY = currentMousePos.y;

                        ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
                        ctx.font = 'bold 16px Arial';
                        const textWidth = ctx.measureText(hoveredPath.name).width;
                        const textHeight = 20;
                        const padding = 8;


                        const textX = mouseX + 15;
                        const textY = mouseY + 25;

                        ctx.fillRect(textX - padding, textY - textHeight - padding, textWidth + padding * 2, textHeight + padding * 2);

                        ctx.fillStyle = '#00FFFF';
                        ctx.textAlign = 'left';
                        ctx.textBaseline = 'top';
                        ctx.fillText(hoveredPath.name, textX, textY - textHeight);


                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                    }
                }
                return;
            }


            if (element.type === 'vertex') {
                const p = worldToPixel(element.element.x, element.element.y);
                ctx.strokeStyle = '#00FFFF';
                ctx.lineWidth = 2 / viewScale;
                ctx.beginPath();
                ctx.arc(p.x, p.y, 10 / viewScale, 0, Math.PI * 2);
                ctx.stroke();
            } else if (element.type === 'edge') {
                let fromV, toV;
                if (element.source === 'loaded') {
                    const path = loadedPaths[element.pathIndex];
                    fromV = path.vertices.find(v => v.id === element.element.from);
                    toV = path.vertices.find(v => v.id === element.element.to);
                } else {
                    fromV = vertices.find(v => v.id === element.element.from);
                    toV = vertices.find(v => v.id === element.element.to);
                }

                if (fromV && toV) {
                    const p1 = worldToPixel(fromV.x, fromV.y);
                    const p2 = worldToPixel(toV.x, toV.y);
                    ctx.strokeStyle = '#00FFFF';
                    ctx.lineWidth = 4;
                    ctx.globalAlpha = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(p1.x, p1.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.stroke();
                    ctx.globalAlpha = 1.0;
                }
            }
        }



        canvas.addEventListener('wheel', function(e) {
            e.preventDefault();

            const zoomIntensity = 0.1;
            const delta = e.deltaY > 0 ? -zoomIntensity : zoomIntensity;
            const newScale = Math.max(0.1, Math.min(viewScale * (1 + delta), 10)); // Limit zoom

            // Zoom towards mouse pointer
            const mousePos = getCanvasPos(e);

            // Current map pos under mouse
            const mapPosX = (mousePos.x - viewPan.x) / viewScale;
            const mapPosY = (mousePos.y - viewPan.y) / viewScale;

            // Update scale
            viewScale = newScale;

            // Adjust pan to keep map pos under mouse
            viewPan.x = mousePos.x - mapPosX * viewScale;
            viewPan.y = mousePos.y - mapPosY * viewScale;

            redraw();
        });

        canvas.addEventListener('mousedown', function(e) {
            // Pan with middle mouse button only
            if (e.button === 1) {
                isPanning = true;
                lastPanMousePos = getCanvasPos(e);
                e.preventDefault();
                return;
            }

            // All editing operations only work with left button (button === 0)
            if (e.button !== 0) {
                return;
            }

            const pos = getCanvasPos(e);

            if (isAgvMoveMode) {
                const agv = findAgvAtPixel(pos);
                if (agv) {
                    draggingAgv = agv;
                    agvDragFloor = agv.position.z;
                    selectedAgvId = agv.id;
                    updateAgvList();
                    e.preventDefault();
                    return;
                }
            }

            if (currentMode === 'edit' && editOperation === 'move') {
                const element = findElementAt(pos);

                if (element && element.type === 'vertex') {
                    selectedElement = element;
                    isDragging = true;
                    e.preventDefault();
                }
            }
        });

        canvas.addEventListener('mousemove', function(e) {
            if (isPanning) {
                const currPos = getCanvasPos(e);
                viewPan.x += currPos.x - lastPanMousePos.x;
                viewPan.y += currPos.y - lastPanMousePos.y;
                lastPanMousePos = currPos;
                redraw();
                return;
            }

            if (isDragging && selectedElement && selectedElement.type === 'vertex') {
                const pos = getCanvasPos(e);
                const worldPos = pixelToWorld(pos.x, pos.y);


                selectedElement.element.x = worldPos.x;
                selectedElement.element.y = worldPos.y;


                const vertexId = selectedElement.element.id;
                for (let path of loadedPaths) {
                    if (path.vertices) {
                        const v = path.vertices.find(v => v.id === vertexId);
                        if (v) {
                            v.x = worldPos.x;
                            v.y = worldPos.y;
                        }
                    }
                }

                redraw();
            }
        });

        canvas.addEventListener('mouseup', async function(e) {
            if (isPanning) {
                isPanning = false;
                e.preventDefault();
                return;
            }

            if (draggingAgv && isAgvMoveMode) {
                await persistAgvPosition(draggingAgv);
                draggingAgv = null;
                agvDragFloor = null;
                return;
            }

            if (isDragging && selectedElement && selectedElement.type === 'vertex') {
                isDragging = false;
                const vertexId = selectedElement.element.id;


                try {
                    const response = await fetch(`${API_BASE}/vertices/${vertexId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            x: selectedElement.element.x,
                            y: selectedElement.element.y
                        })
                    });

                    const result = await response.json();
                    if (result.success) {
                        updateInfo(result.message || `Moved vertex ${vertexId}`);
                        await loadAllPaths();
                    } else {
                        alert('Move failed: ' + result.error);
                    }
                } catch (error) {
                    console.error('Move vertex error:', error);
                    alert('Move failed; check that the backend is running');
                }
            }
        });

        canvas.addEventListener('click', function(e) {
            // Only handle left button clicks for editing operations
            if (e.button !== 0) {
                return;
            }

            const pos = getCanvasPos(e);
            const worldPos = pixelToWorld(pos.x, pos.y);

            if (isAgvPlacementMode) {
                pendingAgvPosition = worldPos;
                const posXInput = document.getElementById('agvPosX');
                const posYInput = document.getElementById('agvPosY');
                const floorSelect = document.getElementById('agvFloor');
                if (posXInput) posXInput.value = worldPos.x.toFixed(3);
                if (posYInput) posYInput.value = worldPos.y.toFixed(3);
                if (floorSelect && typeof worldPos.z !== 'undefined') {
                    floorSelect.value = String(worldPos.z);
                }
                isAgvPlacementMode = false;
                document.getElementById('createAgvModal').style.display = 'block';
                updateInfo(`Position selected (X:${worldPos.x.toFixed(2)}, Y:${worldPos.y.toFixed(2)}). Complete the AGV settings.`);
                return;
            }

            if (currentMode === 'task-select') {
                const element = findElementAt(pos);
                if (element && element.type === 'vertex') {
                    completeTaskVertexSelection(element.element.id);
                } else {
                    updateInfo('No vertex selected; click near a node');
                }
                return;
            }

            if (currentMode === 'edit') {
                // Edit mode
                if (editOperation === 'insert') {

                    const nearest = findNearestEdge(pos, 30);
                    if (nearest) {
                        insertVertexInEdge(nearest, worldPos);
                    } else {
                        updateInfo('No nearby edge; click closer to an edge');
                    }
                } else if (editOperation === 'delete') {

                    const element = findElementAt(pos);
                    if (element && element.type === 'vertex') {

                        deleteElement(element);
                    } else {
                        updateInfo('Click a vertex to delete');
                    }
                }

            } else if (currentMode === 'measure') {
                handleMeasurementClick(worldPos);
                return;
            } else if (currentMode === 'path') {

                let targetVertex = null;

                if (snapEnabled) {

                    targetVertex = findNearbyVertexForSnap(pos, snapRadius);
                }

                if (targetVertex) {


                    let vertexInCurrent = vertices.find(v => v.id === targetVertex.id);

                    if (!vertexInCurrent) {

                        vertexInCurrent = {
                            id: targetVertex.id,
                            x: targetVertex.x,
                            y: targetVertex.y,
                            z: targetVertex.z,
                            type: targetVertex.type || 'waypoint',
                            action: targetVertex.action || null,
                            properties: targetVertex.properties || {}
                        };
                        vertices.push(vertexInCurrent);
                    }


                    if (lastVertex && lastVertex.id !== vertexInCurrent.id) {
                        createEdge(lastVertex.id, vertexInCurrent.id);
                    }

                    lastVertex = vertexInCurrent;
                    updateInfo(`Snapped to vertex: ${vertexInCurrent.id} (vertices: ${vertices.length}, edges: ${edges.length})`);
                } else {

                    const vertex = {
                        id: generateId('V'),
                        x: worldPos.x,
                        y: worldPos.y,
                        z: worldPos.z,
                        type: 'waypoint',
                        action: null,
                        properties: {}
                    };
                    vertices.push(vertex);


                    if (lastVertex) {
                        createEdge(lastVertex.id, vertex.id);
                    }

                    lastVertex = vertex;
                    updateInfo(`New vertex: ${vertex.id} (vertices: ${vertices.length}, edges: ${edges.length})`);
                }

                redraw();
            }
        });

        canvas.addEventListener('contextmenu', function(e) {
            e.preventDefault();

            if (currentMode === 'path' && vertices.length > 0) {
                // finish drawing

                const timestamp = new Date();
                const dateStr = timestamp.toISOString().slice(0, 19).replace(/[:-]/g, '').replace('T', '_');
                const autoName = `Path_${dateStr}`;
                const pathNameInput = document.getElementById('pathNameInput');
                if (pathNameInput) {
                    pathNameInput.value = autoName;
                }


                const pathDefaultDirection = document.getElementById('pathDefaultDirection');
                if (pathDefaultDirection) {
                    pathDefaultDirection.value = currentDefaultDirection;
                }

                document.getElementById('savePathModal').style.display = 'block';
                lastVertex = null;
            }
        });

        canvas.addEventListener('dblclick', function(e) {
            const pos = getCanvasPos(e);
            const element = findElementAt(pos);

            if (element) {
                selectedElement = element;
                showPropertyPanel(element);
                redraw();
            }
        });

        canvas.addEventListener('mousemove', function(e) {
            const pos = getCanvasPos(e);
            const worldPos = pixelToWorld(pos.x, pos.y);


            const coordDisplay = document.getElementById('coordinateDisplay');
            let coordText = `X: ${worldPos.x.toFixed(3)}, Y: ${worldPos.y.toFixed(3)}, Z: ${worldPos.z}`;

            currentMousePos = pos;

            if (currentMode === 'measure' && measurePoints.length > 0) {
                redraw();
            }

            if (isAgvMoveMode && draggingAgv && agvDragFloor === mapData[currentMap].floor) {
                hideHoverTooltip();
                draggingAgv.position = {
                    x: worldPos.x,
                    y: worldPos.y,
                    z: draggingAgv.position.z
                };
                redraw();
                return;
            }


            if (currentMode === 'edit' && editOperation === 'insert') {
                const nearest = findNearestEdge(pos, 30);
                if (nearest) {
                    hoveredEdge = nearest;
                    coordText += ` | can be inserted on edge ${nearest.edge.id}`;
                } else {
                    hoveredEdge = null;
                }
            } else {
                hoveredEdge = null;
            }


            const element = findElementAt(pos);
            const agvTarget = findAgvAtPixel(pos);


            if (element && element.source === 'loaded' && element.pathIndex !== undefined) {
                hoveredPath = loadedPaths[element.pathIndex];
                coordText += ` | Path: ${hoveredPath.name}`;
            } else {
                hoveredPath = null;
            }

            coordDisplay.textContent = coordText;
            coordDisplay.style.display = 'block';

            const tooltipTarget = element || (agvTarget ? { type: 'agv', element: agvTarget } : null);
            updateHoverTooltip(tooltipTarget, e);

            if (element !== hoveredElement) {
                hoveredElement = element;
                redraw();
            }


            if (currentMode === 'path' || currentMode === 'edit') {
                redraw();
            }
        });

        canvas.addEventListener('mouseleave', function() {
            document.getElementById('coordinateDisplay').style.display = 'none';
            hideHoverTooltip();
            currentMousePos = null;
            hoveredElement = null;
            hoveredEdge = null;
            isDragging = false;
            if (draggingAgv) {
                draggingAgv = null;
                agvDragFloor = null;
            }
            redraw();
        });


        document.addEventListener('keydown', function(e) {
            // ESC - Cancel
            if (e.key === 'Escape') {
                currentMode = 'default';
                lastVertex = null;
                selectedElement = null;
                isDragging = false;
                pendingTaskVertexField = null;
                previousModeBeforeTaskSelect = null;
                clearMeasurement();
                document.getElementById('directionControl').style.display = 'none';
                document.getElementById('editControl').style.display = 'none';
                if (isAgvMoveMode) {
                    isAgvMoveMode = false;
                    draggingAgv = null;
                    agvDragFloor = null;
                    const moveBtn = document.getElementById('moveAgvBtn');
                    if (moveBtn) moveBtn.classList.remove('active');
                }
                closePropertyPanel();
                updateToolbarState();
                redraw();
            }



            // H - Help
            if (e.key === 'h' || e.key === 'H') {
                toggleHelpPanel();
            }

            // Ctrl+S - Save
            if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                if (vertices.length > 0) {

                    const timestamp = new Date();
                    const dateStr = timestamp.toISOString().slice(0, 19).replace(/[:-]/g, '').replace('T', '_');
                    const autoName = `Path_${dateStr}`;
                    const pathNameInput = document.getElementById('pathNameInput');
                    if (pathNameInput) {
                        pathNameInput.value = autoName;
                    }


                    const pathDefaultDirection = document.getElementById('pathDefaultDirection');
                    if (pathDefaultDirection) {
                        pathDefaultDirection.value = currentDefaultDirection;
                    }

                    document.getElementById('savePathModal').style.display = 'block';
                }
            }

            // Ctrl+Z - undo the last vertex
            if (e.ctrlKey && e.key === 'z' && currentMode === 'path') {
                e.preventDefault();
                if (vertices.length > 0) {
                    const lastV = vertices[vertices.length - 1];

                    edges = edges.filter(e => e.from !== lastV.id && e.to !== lastV.id);
                    vertices.pop();
                    lastVertex = vertices.length > 0 ? vertices[vertices.length - 1] : null;
                    redraw();
                    updateInfo(`Undo complete; remaining ${vertices.length} vertices`);
                }
            }
        });



        document.getElementById('mapSelect').addEventListener('change', function() {
            currentMap = this.value;
            clearMeasurement();
            loadMap(currentMap);
        });

        document.getElementById('pathBtn').addEventListener('click', function() {
            if (currentMode === 'path') {
                currentMode = 'default';
                lastVertex = null;
                document.getElementById('directionControl').style.display = 'none';
            } else {
                currentMode = 'path';
                document.getElementById('directionControl').style.display = 'block';
                updateInfo('Draw mode: click to add vertices; right-click to finish');
            }
            updateToolbarState();
            redraw();
        });

        document.getElementById('drawDirectionSelect').addEventListener('change', function() {
            currentDefaultDirection = this.value;
            updateInfo(`Switch to ${this.value === 'bidirectional' ? 'Bidirectional' : 'Unidirectional'} drawing mode`);
        });

        document.getElementById('measureBtn').addEventListener('click', function() {
            if (currentMode === 'measure') {
                currentMode = 'default';
                clearMeasurement();
                updateInfo('Measure mode disabled');
            } else {
                currentMode = 'measure';
                clearMeasurement();
                updateInfo('Measure mode: click two points');
            }
            updateToolbarState();
            redraw();
        });

        document.getElementById('editBtn').addEventListener('click', function() {
            if (currentMode === 'edit') {
                currentMode = 'default';
                document.getElementById('editControl').style.display = 'none';
                isDragging = false;
            } else {
                currentMode = 'edit';
                document.getElementById('editControl').style.display = 'block';
                editOperation = document.getElementById('editOperationSelect').value;
                updateInfo(`Edit mode: ${editOperation === 'move' ? 'move' : editOperation === 'insert' ? 'insert' : 'delete'} Vertex`);
            }
            updateToolbarState();
            redraw();
        });

        document.getElementById('editOperationSelect').addEventListener('change', function() {
            editOperation = this.value;
            updateInfo(`Edit mode: ${editOperation === 'move' ? 'move' : editOperation === 'insert' ? 'insert' : 'delete'} Vertex`);
        });

        document.getElementById('clearBtn').addEventListener('click', function() {
            if (confirm('Clear the current path?')) {
                vertices = [];
                edges = [];
                lastVertex = null;
                selectedElement = null;
                currentMode = 'default';
                document.getElementById('directionControl').style.display = 'none';
                updateToolbarState();
                updateInfo('Cleared');
                redraw();
            }
        });


        const createTaskBtn = document.getElementById('createTaskBtn');
        if (createTaskBtn) {
            createTaskBtn.addEventListener('click', openTaskModal);
        }

        const selectStartVertexBtn = document.getElementById('selectStartVertexBtn');
        if (selectStartVertexBtn) {
            selectStartVertexBtn.addEventListener('click', () => beginTaskVertexSelection('start'));
        }


        const taskEndVerticesContainer = document.getElementById('taskEndVerticesContainer');
        if (taskEndVerticesContainer) {
            taskEndVerticesContainer.addEventListener('click', (e) => {
                const selectBtn = e.target.closest('.select-end-vertex-btn');
                if (selectBtn) {
                    const endIndex = parseInt(selectBtn.getAttribute('data-end-index'));
                    beginTaskVertexSelection('end', endIndex);
                }

                const removeBtn = e.target.closest('.remove-end-vertex-btn');
                if (removeBtn) {
                    const endIndex = parseInt(removeBtn.getAttribute('data-end-index'));
                    removeEndVertexFromModal(endIndex);
                }
            });
        }

        const addEndVertexBtn = document.getElementById('addEndVertexBtn');
        if (addEndVertexBtn) {
            addEndVertexBtn.addEventListener('click', addEndVertexToModal);
        }

        const confirmCreateTaskBtn = document.getElementById('confirmCreateTaskBtn');
        if (confirmCreateTaskBtn) {
            confirmCreateTaskBtn.addEventListener('click', confirmCreateTask);
        }

        const createSceneBtn = document.getElementById('createSceneBtn');
        if (createSceneBtn) {
            createSceneBtn.addEventListener('click', () => openSceneModal('createSceneModal'));
        }

        const loadSceneBtn = document.getElementById('loadSceneBtn');
        if (loadSceneBtn) {
            loadSceneBtn.addEventListener('click', () => openSceneModal('loadSceneModal'));
        }

        const exitSceneBtn = document.getElementById('exitSceneBtn');
        if (exitSceneBtn) {
            exitSceneBtn.addEventListener('click', exitScene);
        }

        const saveSceneBtn = document.getElementById('saveSceneBtn');
        if (saveSceneBtn) {
            saveSceneBtn.addEventListener('click', saveSceneExplicit);
        }

        const confirmCreateSceneBtn = document.getElementById('confirmCreateSceneBtn');
        if (confirmCreateSceneBtn) {
            confirmCreateSceneBtn.addEventListener('click', handleCreateSceneConfirm);
        }

        const confirmLoadSceneBtn = document.getElementById('confirmLoadSceneBtn');
        if (confirmLoadSceneBtn) {
            confirmLoadSceneBtn.addEventListener('click', handleLoadSceneConfirm);
        }

        const confirmGenerateTaskBtn = document.getElementById('confirmGenerateTaskBtn');
        if (confirmGenerateTaskBtn) {
            confirmGenerateTaskBtn.addEventListener('click', handleGenerateTaskConfirm);
        }

        document.getElementById('createAgvBtn').addEventListener('click', function() {
            if (!currentMap) {
                alert('Load a scene before creating an AGV');
                return;
            }
            isAgvPlacementMode = true;
            pendingAgvPosition = null;
            closeCreateAgvModal();
            updateInfo('Click the canvas to select the AGV start position');
        });

        document.getElementById('moveAgvBtn').addEventListener('click', function() {
            isAgvMoveMode = !isAgvMoveMode;
            this.classList.toggle('active', isAgvMoveMode);
            if (isAgvMoveMode) {
                currentMode = 'default';
                document.getElementById('directionControl').style.display = 'none';
                document.getElementById('editControl').style.display = 'none';
                updateToolbarState();
                updateInfo('Move AGV mode: drag an AGV to reposition it');
            } else {
                draggingAgv = null;
                updateInfo('Move AGV mode disabled');
            }
            redraw();
        });

        document.getElementById('snapToVertex').addEventListener('change', function() {
            snapEnabled = this.checked;
        });

        document.getElementById('snapRadius').addEventListener('input', function() {
            snapRadius = parseInt(this.value);
            document.getElementById('snapRadiusValue').textContent = snapRadius;
        });


        document.getElementById('showGridCheckbox').addEventListener('change', function() {
            showGrid = this.checked;
            redraw();
        });

        document.getElementById('gridSizeSlider').addEventListener('input', function() {
            gridSize = parseFloat(this.value);
            document.getElementById('gridSizeValue').textContent = gridSize.toFixed(1);
            if (showGrid) {
                redraw();
            }
        });




        let currentDefaultDirection = 'bidirectional';

        function createEdge(fromId, toId) {

            const exists = edges.find(e =>
                (e.from === fromId && e.to === toId) ||
                (e.from === toId && e.to === fromId)
            );

            if (exists) {
                updateInfo('This connection already exists');
                return;
            }


            const fromV = vertices.find(v => v.id === fromId);
            const toV = vertices.find(v => v.id === toId);

            if (!fromV || !toV) {
                console.error('Vertex not found:', fromId, toId);
                updateInfo('Error: vertex not found');
                return;
            }

            const length = worldDistance(fromV, toV);

            const edge = {
                id: generateId('E'),
                from: fromId,
                to: toId,
                direction: currentDefaultDirection,
                length: parseFloat(length.toFixed(3)),
                cost: parseFloat(length.toFixed(3)),
                max_speed: 1.5,
                width: 0.6,
                action: null
            };

            edges.push(edge);
        }


        function removeOrphanVertices() {
            if (!vertices || vertices.length === 0) return;
            if (!edges || edges.length === 0) {

                vertices = [];
                return;
            }


            const connectedVertexIds = new Set();
            edges.forEach(edge => {
                connectedVertexIds.add(edge.from);
                connectedVertexIds.add(edge.to);
            });


            const originalCount = vertices.length;
            vertices = vertices.filter(v => connectedVertexIds.has(v.id));

            if (vertices.length < originalCount) {
                const removedCount = originalCount - vertices.length;
                updateInfo(`Removed ${removedCount} isolated vertices without edges`);
            }
        }


        function removeOrphanVerticesFromPath(path) {
            if (!path.vertices || path.vertices.length === 0) return;
            if (!path.edges || path.edges.length === 0) {

                path.vertices = [];
                return;
            }


            const connectedVertexIds = new Set();
            path.edges.forEach(edge => {
                connectedVertexIds.add(edge.from);
                connectedVertexIds.add(edge.to);
            });


            const originalCount = path.vertices.length;
            path.vertices = path.vertices.filter(v => connectedVertexIds.has(v.id));

            if (path.vertices.length < originalCount) {
                const removedCount = originalCount - path.vertices.length;
                updateInfo(`Removed ${removedCount} isolated vertices without edges`);
            }
        }

        async function deleteElement(element) {

            const elementId = element.element.id;
            const confirmMessage = element.type === 'vertex'
                ? `Delete vertex ${elementId}? This removes it from every path.`
                : `Delete edge ${elementId}?`;

            if (!confirm(confirmMessage)) {
                return;
            }

            if (element.type === 'vertex') {
                const vertexId = element.element.id;


                try {
                    const response = await fetch(`${API_BASE}/vertices/${vertexId}`, {
                        method: 'DELETE'
                    });

                    const result = await response.json();
                    if (result.success) {

                        vertices = vertices.filter(v => v.id !== vertexId);
                        edges = edges.filter(e => e.from !== vertexId && e.to !== vertexId);

                        for (let path of loadedPaths) {
                            if (path.vertices) {
                                path.vertices = path.vertices.filter(v => v.id !== vertexId);
                            }
                            if (path.edges) {
                                path.edges = path.edges.filter(e => e.from !== vertexId && e.to !== vertexId);
                            }
                        }

                        updateInfo(result.message || `Deleted vertex ${vertexId}`);
                        await loadAllPaths();
                        redraw();
                    } else {
                        alert('Delete failed: ' + result.error);
                    }
                } catch (error) {
                    console.error('Delete vertex error:', error);
                    alert('Delete failed; check that the backend is running');
                }
            } else if (element.type === 'edge') {

                if (element.source === 'loaded') {
                    const path = loadedPaths[element.pathIndex];
                    const edgeId = element.element.id;
                    path.edges = path.edges.filter(e => e.id !== edgeId);


                    removeOrphanVerticesFromPath(path);

                    updateInfo(`Removed edge from path ${path.name}: edge ${edgeId}`);
                    await updatePathToServer(path);
                } else {
                    const edgeId = element.element.id;
                    edges = edges.filter(e => e.id !== edgeId);


                    removeOrphanVertices();

                    updateInfo(`Deleted edge ${edgeId}`);
                }
                redraw();
            }

            selectedElement = null;
            closePropertyPanel();
        }

        function showPropertyPanel(element) {
            const panel = document.getElementById('propertyPanel');
            const content = document.getElementById('propertyContent');
            const title = document.getElementById('propertyTitle');


            let sourceInfo = '';
            if (element.type === 'vertex') {

                const vertexId = element.element.id;
                const usedInPaths = [];
                for (let path of loadedPaths) {
                    if (path.vertices && path.vertices.some(v => v.id === vertexId)) {
                        usedInPaths.push(path.name);
                    }
                }
                if (usedInPaths.length > 0) {
                    sourceInfo = `<div style="background: #fff3cd; padding: 8px; border-radius: 4px; margin-bottom: 10px; font-size: 12px;">
                        Warning: This vertex is used by  <strong>${usedInPaths.length}</strong>  paths: ${usedInPaths.join(', ')}<br>
                        <small>Changes update every path</small>
                    </div>`;
                } else if (element.source === 'loaded') {
                    const path = loadedPaths[element.pathIndex];
                    sourceInfo = `<div style="background: #e3f2fd; padding: 8px; border-radius: 4px; margin-bottom: 10px; font-size: 12px;">
                         Path: <strong>${path.name}</strong>
                    </div>`;
                }
            } else if (element.source === 'loaded') {
                const path = loadedPaths[element.pathIndex];
                sourceInfo = `<div style="background: #e3f2fd; padding: 8px; border-radius: 4px; margin-bottom: 10px; font-size: 12px;">
                     Path: <strong>${path.name}</strong>
                </div>`;
            }

            if (element.type === 'vertex') {
                title.textContent = 'Vertex Properties';
                content.innerHTML = sourceInfo + `
                    <div class="property-group">
                        <label>ID:</label>
                        <input type="text" id="prop_id" value="${element.element.id}" readonly>
                    </div>
                    <div class="property-group">
                        <label>Coordinates X:</label>
                        <input type="number" id="prop_x" value="${element.element.x.toFixed(3)}" step="0.001">
                    </div>
                    <div class="property-group">
                        <label>Coordinates Y:</label>
                        <input type="number" id="prop_y" value="${element.element.y.toFixed(3)}" step="0.001">
                    </div>
                    <div class="property-group">
                        <label>Floor Z:</label>
                        <input type="number" id="prop_z" value="${element.element.z}" readonly>
                    </div>
                    <div class="property-group">
                        <label>Type:</label>
                        <select id="prop_type">
                            <option value="waypoint" ${element.element.type === 'waypoint' ? 'selected' : ''}>Waypoint</option>
                            <option value="work_station" ${element.element.type === 'work_station' ? 'selected' : ''}>Work station</option>
                            <option value="elevator_entrance" ${element.element.type === 'elevator_entrance' ? 'selected' : ''}>Elevator entrance</option>
                            <option value="charging_station" ${element.element.type === 'charging_station' ? 'selected' : ''}>Charging station</option>
                            <option value="standby_point" ${element.element.type === 'standby_point' ? 'selected' : ''}>Standby point</option>
                        </select>
                    </div>
                    <div class="property-group">
                        <label>Action:</label>
                        <select id="prop_action">
                            <option value="" ${!element.element.action ? 'selected' : ''}>None</option>
                            <option value="request_entry" ${element.element.action === 'request_entry' ? 'selected' : ''}>Request entry</option>
                            <option value="dock" ${element.element.action === 'dock' ? 'selected' : ''}>Dock</option>
                            <option value="pick" ${element.element.action === 'pick' ? 'selected' : ''}>Pick</option>
                            <option value="drop" ${element.element.action === 'drop' ? 'selected' : ''}>Drop</option>
                            <option value="wait_lift" ${element.element.action === 'wait_lift' ? 'selected' : ''}>Wait for elevator</option>
                            <option value="take_lift" ${element.element.action === 'take_lift' ? 'selected' : ''}>Enter elevator</option>
                            <option value="release_lift" ${element.element.action === 'release_lift' ? 'selected' : ''}>Exit elevator</option>
                        </select>
                    </div>
                    <div class="property-group">
                        <label style="display: inline-flex; align-items: center; cursor: pointer;">
                            <input type="checkbox" id="prop_block" ${element.element.properties && element.element.properties.block ? 'checked' : ''} style="margin-right: 5px;">
                            Blocking action - wait for completion
                        </label>
                    </div>
                    <div class="property-buttons">
                        <button class="btn-save" onclick="saveVertexProperties()">Save</button>
                        <button class="btn-delete" onclick="deleteCurrentElement()">delete</button>
                        <button class="btn-cancel" onclick="closePropertyPanel()">Cancel</button>
                    </div>
                `;
            } else if (element.type === 'edge') {
                title.textContent = 'Edge Properties';
                content.innerHTML = sourceInfo + `
                    <div class="property-group">
                        <label>ID:</label>
                        <input type="text" id="prop_id" value="${element.element.id}" readonly>
                    </div>
                    <div class="property-group">
                        <label>From vertex:</label>
                        <input type="text" id="prop_from" value="${element.element.from}" readonly>
                    </div>
                    <div class="property-group">
                        <label>To vertex:</label>
                        <input type="text" id="prop_to" value="${element.element.to}" readonly>
                    </div>
                    <div class="property-group">
                        <label>Direction:</label>
                        <select id="prop_direction">
                            <option value="unidirectional" ${element.element.direction === 'unidirectional' ? 'selected' : ''}>Unidirectional</option>
                            <option value="bidirectional" ${element.element.direction === 'bidirectional' ? 'selected' : ''}>Bidirectional</option>
                        </select>
                    </div>
                    <div class="property-group">
                        <label>Length (m):</label>
                        <input type="number" id="prop_length" value="${element.element.length}" step="0.1">
                    </div>
                    <div class="property-group">
                        <label>Cost:</label>
                        <input type="number" id="prop_cost" value="${element.element.cost}" step="0.1">
                    </div>
                    <div class="property-group">
                        <label>Maximum speed (m/s):</label>
                        <input type="number" id="prop_max_speed" value="${element.element.max_speed}" step="0.1">
                    </div>
                    <div class="property-group">
                        <label>Width (m):</label>
                        <input type="number" id="prop_width" value="${element.element.width || 0.6}" step="0.1">
                    </div>
                    <div class="property-group">
                        <label>Action:</label>
                        <select id="prop_action_type">
                            <option value="" ${!element.element.action ? 'selected' : ''}>None</option>
                            <option value="play_voice" ${element.element.action?.type === 'play_voice' ? 'selected' : ''}>Play voice prompt</option>
                            <option value="call_door" ${element.element.action?.type === 'call_door' ? 'selected' : ''}>Open door</option>
                            <option value="call_elevator" ${element.element.action?.type === 'call_elevator' ? 'selected' : ''}>Call elevator</option>
                        </select>
                    </div>
                    <div class="property-group">
                        <label>Action parameters (JSON):</label>
                        <textarea id="prop_action_params">${element.element.action ? JSON.stringify(element.element.action.params || {}, null, 2) : '{}'}</textarea>
                    </div>
                    <div class="property-buttons">
                        <button class="btn-save" onclick="saveEdgeProperties()">Save</button>
                        <button class="btn-delete" onclick="deleteCurrentElement()">delete</button>
                        <button class="btn-cancel" onclick="closePropertyPanel()">Cancel</button>
                    </div>
                `;
            }

            panel.style.display = 'block';
        }

        function closePropertyPanel() {
            document.getElementById('propertyPanel').style.display = 'none';
        }

        async function saveVertexProperties() {
            if (!selectedElement || selectedElement.type !== 'vertex') return;

            const vertex = selectedElement.element;
            const vertexId = vertex.id;


            const updateData = {
                x: parseFloat(document.getElementById('prop_x').value),
                y: parseFloat(document.getElementById('prop_y').value),
                type: document.getElementById('prop_type').value,
                action: document.getElementById('prop_action').value || null,
                properties: {
                    ...(vertex.properties || {}),
                    block: document.getElementById('prop_block').checked
                }
            };


            try {
                const response = await fetch(`${API_BASE}/vertices/${vertexId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData)
                });

                const result = await response.json();
                if (result.success) {

                    vertex.x = updateData.x;
                    vertex.y = updateData.y;
                    vertex.type = updateData.type;
                    vertex.action = updateData.action;
                    vertex.properties = updateData.properties;


                    for (let path of loadedPaths) {
                        if (path.vertices) {
                            const v = path.vertices.find(v => v.id === vertexId);
                            if (v) {
                                v.x = updateData.x;
                                v.y = updateData.y;
                                v.type = updateData.type;
                                v.action = updateData.action;
                                v.properties = updateData.properties;
                            }
                        }
                    }

                    updateInfo(result.message || `Updated vertex ${vertexId}`);
                    await loadAllPaths();
                    redraw();
                } else {
                    alert('Update failed: ' + result.error);
                }
            } catch (error) {
                console.error('Update vertex error:', error);
                alert('Update failed; check that the backend is running');
            }

            closePropertyPanel();
        }

        async function saveEdgeProperties() {
            if (!selectedElement || selectedElement.type !== 'edge') return;

            const edge = selectedElement.element;
            const edgeId = edge.id;


            const widthValue = parseFloat(document.getElementById('prop_width').value);
            const updateData = {
                direction: document.getElementById('prop_direction').value,
                length: parseFloat(document.getElementById('prop_length').value),
                cost: parseFloat(document.getElementById('prop_cost').value),
                max_speed: parseFloat(document.getElementById('prop_max_speed').value),
                width: isNaN(widthValue) ? 0.6 : widthValue
            };

            const actionType = document.getElementById('prop_action_type').value;
            if (actionType) {
                try {
                    const params = JSON.parse(document.getElementById('prop_action_params').value);
                    updateData.action = { type: actionType, params: params };
                } catch (e) {
                    alert('Invalid action parameter JSON');
                    return;
                }
            } else {
                updateData.action = null;
            }


            try {
                const response = await fetch(`${API_BASE}/edges/${edgeId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData)
                });

                const result = await response.json();
                if (result.success) {

                    edge.direction = updateData.direction;
                    edge.length = updateData.length;
                    edge.cost = updateData.cost;
                    edge.max_speed = updateData.max_speed;
                    edge.width = updateData.width;
                    edge.action = updateData.action;


                    for (let path of loadedPaths) {
                        if (path.edges) {
                            const e = path.edges.find(e => e.id === edgeId);
                            if (e) {
                                Object.assign(e, updateData);
                            }
                        }
                    }

                    updateInfo(result.message || `Updated edge ${edgeId}`);




                    redraw();
                } else {
                    alert('Update failed: ' + result.error);
                }
            } catch (error) {
                console.error('Update edge error:', error);
                alert('Update failed; check that the backend is running');
            }

            closePropertyPanel();
        }

        function deleteCurrentElement() {

            if (selectedElement) {
                deleteElement(selectedElement);
            }
        }

        function updateToolbarState() {
            const effectiveMode = currentMode === 'task-select' ? 'default' : currentMode;
            document.getElementById('pathBtn').classList.toggle('active', effectiveMode === 'path');
            document.getElementById('measureBtn').classList.toggle('active', effectiveMode === 'measure');
            document.getElementById('editBtn').classList.toggle('active', effectiveMode === 'edit');
        }

        // Insert a vertex on an edge
        async function insertVertexInEdge(nearestEdgeInfo, worldPos) {
            const edge = nearestEdgeInfo.edge;
            const pathId = nearestEdgeInfo.path ? nearestEdgeInfo.path.id : null;

            if (!pathId) {
                alert('Vertices can only be inserted into saved paths');
                return;
            }


            let fromVertex, toVertex;
            if (nearestEdgeInfo.path) {
                fromVertex = nearestEdgeInfo.path.vertices.find(v => v.id === edge.from);
                toVertex = nearestEdgeInfo.path.vertices.find(v => v.id === edge.to);
            } else {
                fromVertex = vertices.find(v => v.id === edge.from);
                toVertex = vertices.find(v => v.id === edge.to);
            }

            if (!fromVertex || !toVertex) {
                alert('Edge endpoints not found');
                return;
            }


            const newVertex = {
                id: generateId('V'),
                x: worldPos.x,
                y: worldPos.y,
                z: worldPos.z,
                type: 'waypoint',
                action: null,
                properties: {}
            };


            const length1 = worldDistance(fromVertex, newVertex);
            const length2 = worldDistance(newVertex, toVertex);


            try {
                const response = await fetch(`${API_BASE}/vertices/insert`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        edge_id: edge.id,
                        path_id: pathId,
                        vertex: newVertex,
                        length1: parseFloat(length1.toFixed(3)),
                        length2: parseFloat(length2.toFixed(3)),
                        cost1: parseFloat(length1.toFixed(3)),
                        cost2: parseFloat(length2.toFixed(3))
                    })
                });

                const result = await response.json();
                if (result.success) {
                    updateInfo(result.message || `Inserted vertex into edge ${edge.id}: vertex ${newVertex.id}`);
                    await loadAllPaths();
                    redraw();
                } else {
                    alert('Insert failed: ' + result.error);
                }
            } catch (error) {
                console.error('Insert vertex error:', error);
                alert('Insert failed; check that the backend is running');
            }
        }

        function updateInfo(message) {
            const panel = document.getElementById('infoPanel');
            const content = document.getElementById('infoContent');
            if (!panel || !content) return;
            content.textContent = message;
            panel.classList.add('visible');
            if (infoHideTimer) {
                clearTimeout(infoHideTimer);
            }
            infoHideTimer = setTimeout(() => {
                panel.classList.remove('visible');
            }, 5000);
        }

        function toggleHelpPanel() {
            const panel = document.getElementById('helpPanel');
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }

        function closeHelpPanel() {
            document.getElementById('helpPanel').style.display = 'none';
        }



        function closeSavePathModal() {
            document.getElementById('savePathModal').style.display = 'none';
            document.getElementById('pathNameInput').value = '';
        }

        async function confirmSavePath() {
            const name = document.getElementById('pathNameInput').value.trim();
            const defaultDirection = document.getElementById('pathDefaultDirection').value;

            if (!name) {
                alert('Enter a path name');
                return;
            }



            edges.forEach(edge => {
                edge.direction = defaultDirection;
            });

            const pathData = {
                name: name,
                floor: mapData[currentMap].floor,
                vertices: vertices,
                edges: edges
            };

            try {
                const response = await fetch(`${API_BASE}/paths`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(pathData)
                });

                const result = await response.json();
                if (result.success) {
                    closeSavePathModal();


                    loadedPaths.push(result.path);


                    vertices = [];
                    edges = [];
                    lastVertex = null;

                    updateToolbarState();
                    redraw();
                    updateInfo('Path saved; you can draw another');

                } else {
                    alert('Save failed: ' + result.error);
                }
            } catch (error) {
                console.error('Save path error:', error);
                alert('Save failed; check that the backend is running');
            }
        }


        function openSceneModal(id) {

            if (id === 'loadSceneModal' && currentScene) {
                alert('Exit the current scene before loading another');
                return;
            }

            const modal = document.getElementById(id);
            if (!modal) return;
            if (id === 'loadSceneModal') {
                refreshSceneOptions();
            }
            modal.style.display = 'block';
        }

        function closeSceneModal(id) {
            const modal = document.getElementById(id);
            if (modal) {
                modal.style.display = 'none';
            }
        }

        function openTaskModal() {
            if (!isSceneActive()) {
                alert('Create or load a scene before creating a task');
                return;
            }
            resetTaskForm();
            const modal = document.getElementById('createTaskModal');
            if (modal) modal.style.display = 'block';
            taskModalHiddenForSelection = false;
        }

        function closeTaskModal() {
            const modal = document.getElementById('createTaskModal');
            if (modal) modal.style.display = 'none';
            taskModalHiddenForSelection = false;
            cancelTaskVertexSelection(false);
        }

        function openGenerateTaskModal() {
            if (!isSceneActive()) {
                alert('Create or load a scene before generating tasks');
                return;
            }

            document.getElementById('generateTaskCount').value = '5';
            document.getElementById('generateTaskDuration').value = '10';
            document.getElementById('generateTaskPriorityLow').value = '33';
            document.getElementById('generateTaskPriorityMedium').value = '34';
            document.getElementById('generateTaskPriorityHigh').value = '33';
            document.getElementById('generateTaskDeadlineMin').value = '3';
            document.getElementById('generateTaskDeadlineMax').value = '5';
            const modal = document.getElementById('generateTaskModal');
            if (modal) modal.style.display = 'block';
        }

        function closeGenerateTaskModal() {
            const modal = document.getElementById('generateTaskModal');
            if (modal) modal.style.display = 'none';
        }

        function resetTaskForm() {
            document.getElementById('taskNameInput').value = '';
            document.getElementById('taskStartVertex').value = '';


            const container = document.getElementById('taskEndVerticesContainer');
            if (container) {
                container.innerHTML = '';
                updateEndVerticesCount();
            }

            document.getElementById('taskPriorityInput').value = 'medium';
            document.getElementById('taskStartTimeInput').value = '';
            document.getElementById('taskDeadlineInput').value = '';
        }

        function addEndVertexToModal() {
            const container = document.getElementById('taskEndVerticesContainer');
            if (!container) return;

            const existingItems = container.querySelectorAll('.task-end-vertex-item');
            const newIndex = existingItems.length;

            const newItem = document.createElement('div');
            newItem.className = 'task-end-vertex-item task-vertex-row';
            newItem.innerHTML = `
                <input type="text" class="task-end-vertex-input" data-end-index="${newIndex}" readonly placeholder="Click to select" />
                <button type="button" class="btn-small secondary select-end-vertex-btn" data-end-index="${newIndex}">Select</button>
                <button type="button" class="btn-small danger remove-end-vertex-btn" data-end-index="${newIndex}">delete</button>
            `;
            container.appendChild(newItem);
            updateEndVerticesCount();
        }

        function removeEndVertexFromModal(endIndex) {
            const container = document.getElementById('taskEndVerticesContainer');
            if (!container) return;

            const allItems = container.querySelectorAll('.task-end-vertex-item');
            const itemToRemove = container.querySelector(`.task-end-vertex-item [data-end-index="${endIndex}"]`)?.closest('.task-end-vertex-item');
            if (itemToRemove) {
                itemToRemove.remove();

                const remainingItems = container.querySelectorAll('.task-end-vertex-item');
                remainingItems.forEach((item, idx) => {
                    const input = item.querySelector('.task-end-vertex-input');
                    const selectBtn = item.querySelector('.select-end-vertex-btn');
                    const removeBtn = item.querySelector('.remove-end-vertex-btn');
                    if (input) {
                        input.setAttribute('data-end-index', idx);
                    }
                    if (selectBtn) selectBtn.setAttribute('data-end-index', idx);
                    if (removeBtn) removeBtn.setAttribute('data-end-index', idx);
                });
                updateEndVerticesCount();
            }
        }

        function updateEndVerticesCount() {
            const container = document.getElementById('taskEndVerticesContainer');
            const countElement = document.getElementById('taskEndVerticesCount');
            if (container && countElement) {
                const count = container.querySelectorAll('.task-end-vertex-item').length;
                countElement.textContent = `(${count} destinations)`;
            }
        }

        function cancelTaskVertexSelection(restoreModal = true) {
            if (pendingTaskVertexField) {
                currentMode = previousModeBeforeTaskSelect || 'default';
                pendingTaskVertexField = null;
                pendingTaskEndIndex = null;
                previousModeBeforeTaskSelect = null;
                updateToolbarState();
            }
            if (taskModalHiddenForSelection) {
                if (restoreModal) {
                    const modal = document.getElementById('createTaskModal');
                    if (modal) modal.style.display = 'block';
                }
                taskModalHiddenForSelection = false;
            }
        }

        let pendingTaskEndIndex = null;

        function beginTaskVertexSelection(field, endIndex = null) {
            if (!isSceneActive()) {
                alert('Create or load a scene first');
                return;
            }
            const taskModal = document.getElementById('createTaskModal');
            if (taskModal && taskModal.style.display !== 'none') {
                taskModal.style.display = 'none';
                taskModalHiddenForSelection = true;
            }
            pendingTaskVertexField = field;
            pendingTaskEndIndex = endIndex;
            previousModeBeforeTaskSelect = currentMode;
            currentMode = 'task-select';
            updateToolbarState();
            if (field === 'start') {
                updateInfo('Click the task start vertex');
            } else {
                const endNum = endIndex !== null ? endIndex + 1 : 1;
                updateInfo(`Click destination ${endNum} for the task`);
            }
        }

        function completeTaskVertexSelection(vertexId) {
            if (!pendingTaskVertexField) return;

            if (pendingTaskVertexField === 'start') {
                const input = document.getElementById('taskStartVertex');
                if (input) {
                    input.value = vertexId;
                }
            } else {

                const container = document.getElementById('taskEndVerticesContainer');
                if (container && pendingTaskEndIndex !== null) {
                    const input = container.querySelector(`.task-end-vertex-input[data-end-index="${pendingTaskEndIndex}"]`);
                    if (input) {
                        input.value = vertexId;
                    }
                }
            }

            pendingTaskEndIndex = null;
            cancelTaskVertexSelection();
        }

        async function confirmCreateTask() {
            if (!isSceneActive()) {
                alert('Create or load a scene first');
                return;
            }
            const name = document.getElementById('taskNameInput').value.trim() || 'Unnamed task';
            const startVertex = document.getElementById('taskStartVertex').value.trim();


            const container = document.getElementById('taskEndVerticesContainer');
            const endVertexInputs = container ? container.querySelectorAll('.task-end-vertex-input') : [];
            const endVertices = Array.from(endVertexInputs)
                .map(input => input.value.trim())
                .filter(v => v);

            const priority = document.getElementById('taskPriorityInput').value;
            const startTime = document.getElementById('taskStartTimeInput').value.trim();
            const deadline = document.getElementById('taskDeadlineInput').value.trim();

            if (!startVertex) {
                alert('Select the task start vertex');
                return;
            }


            const timePattern = /^(\d{1,3}):([0-5][0-9])$/;
            if (startTime && !timePattern.test(startTime)) {
                alert('Invalid start time; use MM:SS, for example 05:30');
                return;
            }
            if (deadline && !timePattern.test(deadline)) {
                alert('Invalid deadline; use MM:SS, for example 10:45');
                return;
            }

            const newTask = {
                id: generateId('T'),
                name,
                start_vertex: startVertex,
                end_vertex: endVertices[0] || '',
                end_vertices: endVertices,
                priority,
                start_time: startTime || null,
                deadline: deadline || null,
                status: 'pending',
                created_at: new Date().toISOString()
            };
            tasks.push(normalizeTask(newTask));
            updateTaskListPanel();
            await persistSceneData();
            closeTaskModal();
        }

        async function updatePathToServer(path) {
            try {
                const response = await fetch(`${API_BASE}/paths/${path.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(path)
                });

                const result = await response.json();
                if (!result.success) {
                    console.error('Update path failed:', result.error);
                }
            } catch (error) {
                console.error('Update path error:', error);
            }
        }

        function closeCreateAgvModal() {
            document.getElementById('createAgvModal').style.display = 'none';
        }

        async function confirmCreateAgv() {
            const name = document.getElementById('agvNameInput').value.trim();
            const x = parseFloat(document.getElementById('agvPosX').value);
            const y = parseFloat(document.getElementById('agvPosY').value);
            const z = parseInt(document.getElementById('agvFloor').value);
            const length = parseFloat(document.getElementById('agvLength').value) || 0.7;
            const width = parseFloat(document.getElementById('agvWidth').value) || 0.5;
            const maxSpeedInput = parseFloat(document.getElementById('agvMaxSpeed').value);
            const maxSpeed = Number.isFinite(maxSpeedInput) && maxSpeedInput > 0 ? maxSpeedInput : 1.0;

            if (!name) {
                alert('Enter an AGV name');
                return;
            }

            const agvData = {
                name: name,
                position: { x, y, z },
                orientation: 0,
                status: 'idle',
                length,
                width,
                max_speed: maxSpeed
            };

            try {
                const response = await fetch(`${API_BASE}/agvs`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agvData)
                });

                const result = await response.json();
                if (result.success) {
                    agvListLoaded = true;
                    upsertAgv(result.agv);
                    selectedAgvId = result.agv.id;
                    updateAgvList();
                    closeCreateAgvModal();
                    redraw();

                } else {
                    alert('Create failed: ' + result.error);
                }
            } catch (error) {
                console.error('Create AGV error:', error);
                alert('Create failed; check that the backend is running');
            }
        }

        async function fetchAgvs() {
            try {
                const response = await fetch(`${API_BASE}/agvs`);
                const result = await response.json();
                if (result.success) {
                    agvListLoaded = true;
                    setAgvCollection(result.agvs || []);
                    updateAgvList();
                    redraw();
                    if (isSceneActive()) {

                    }
                }
            } catch (error) {
                console.error('Failed to get AGV list:', error);
            }
        }

        async function updateAgvOnServer(agvId, payload) {
            try {
                const response = await fetch(`${API_BASE}/agvs/${agvId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await response.json();
                if (result.success) {
                    agvListLoaded = true;
                    upsertAgv(result.agv);
                    updateAgvList();
                    redraw();
                    updateInfo(`AGV ${result.agv.name || agvId} updated`);
                } else {
                    alert('Failed to update AGV: ' + result.error);
                }
            } catch (error) {
                console.error('Failed to update AGV:', error);
                alert('Failed to update AGV; check the backend');
            }
        }

        async function persistAgvPosition(agv) {
            await updateAgvOnServer(agv.id, {
                position: agv.position
            });
        }

        async function loadAllPaths() {
            try {
                const response = await fetch(`${API_BASE}/paths`);
                const result = await response.json();

                if (result.success) {
                    loadedPaths = result.paths;
                    redraw();

                } else {
                    alert('Load failed: ' + result.error);
                }
            } catch (error) {
                console.error('Load path error:', error);
                alert('Load failed; check that the backend is running');
            }
        }

        function getAgvKey(agv) {
            if (!agv) return '';
            const name = (agv.name || '').trim();
            if (name) return name.toLowerCase();
            return agv.id || '';
        }

        function setAgvCollection(list) {
            const map = new Map();
            (list || []).forEach(item => {
                const key = getAgvKey(item);
                if (!key) return;
                map.set(key, item);
            });
            agvs = Array.from(map.values());
        }

        function upsertAgv(agv) {
            const key = getAgvKey(agv);
            if (!key) return;
            let replaced = false;
            agvs = agvs.map(item => {
                if (getAgvKey(item) === key) {
                    replaced = true;

                    const merged = { ...item, ...agv };

                    if (agv.sim_state) {
                        merged.simState = {
                            edgeIdx: agv.sim_state.edge_idx || 0,
                            dist: agv.sim_state.dist || 0,
                            finished: false
                        };
                    }
                    return merged;
                }
                return item;
            });
            if (!replaced) {

                if (agv.sim_state) {
                    agv.simState = {
                        edgeIdx: agv.sim_state.edge_idx || 0,
                        dist: agv.sim_state.dist || 0,
                        finished: false
                    };
                }
                agvs.push(agv);
            }
        }

        const AGV_STATUS_LABELS = {
            idle: 'Idle',
            moving: 'Running',
            working: 'Working',
            charging: 'Charging',
            error: 'Error'
        };

        const STATUS_CLASS_NAMES = ['idle', 'moving', 'working', 'charging', 'error'];

        function normalizeStatusClass(status) {
            if (!status) return 'idle';
            const normalized = String(status).toLowerCase();
            if (normalized === 'working') return 'moving';
            if (STATUS_CLASS_NAMES.includes(normalized)) {
                return normalized;
            }
            if (normalized.startsWith('moving')) return 'moving';
            if (normalized.includes('wait') || normalized.includes('pending')) return 'moving';
            if (normalized.includes('charge')) return 'charging';
            if (normalized.includes('error') || normalized.includes('fault') || normalized.includes('fail')) return 'error';
            return 'idle';
        }

        function getTaskStatusText(task) {
            if (!task) return 'No tasks';
            if (typeof task === 'string') return task;
            const taskName = task.name || task.id || 'Task';
            let statusLabel = '';
            if (task.status === 'moving_to_dropoff') {
                statusLabel = formatDropoffProgress(task);
            } else {
                statusLabel = task.status ? getTaskStatusLabel(task.status) : '';
            }
            return statusLabel ? `${taskName}  -  ${statusLabel}` : taskName;
        }

        function getListStatusInfo(agv) {
            if (agv.current_task) {
                const label = getTaskStatusText(agv.current_task);
                const phase = typeof agv.current_task === 'object'
                    ? agv.current_task.status
                    : agv.current_task;
                return {
                    label,
                    className: normalizeStatusClass(phase)
                };
            }
            return {
                label: AGV_STATUS_LABELS[agv.status] || agv.status || 'Idle',
                className: normalizeStatusClass(agv.status)
            };
        }

        function renderAgvDetailFields(agv) {
            const { length, width } = getAgvDimensions(agv);
            const maxSpeed = getAgvMaxSpeed(agv);
            const statusLabel = AGV_STATUS_LABELS[agv.status] || agv.status || 'Unknown';
            const statusClass = normalizeStatusClass(agv.status);
            const taskStatus = getTaskStatusText(agv.current_task);
            return `
                <div class="agv-item-detail-header">
                    <strong>${agv.name || agv.id}</strong>
                    <span class="status-pill ${statusClass}">${statusLabel}</span>
                </div>
                <div class="task-meta">Task status: ${taskStatus}</div>
                <div class="agv-field">
                    <label>Status</label>
                    <select class="agv-status">
                        ${Object.keys(AGV_STATUS_LABELS).map(status => `
                            <option value="${status}" ${status === agv.status ? 'selected' : ''}>
                                ${AGV_STATUS_LABELS[status]}
                            </option>`).join('')}
                    </select>
                </div>
                <div class="agv-field">
                    <label>Direction (rad)</label>
                    <input type="number" step="0.1" class="agv-orientation" value="${(agv.orientation || 0).toFixed(2)}">
                </div>
                <div class="agv-field">
                    <label>Length (m)</label>
                    <input type="number" min="0.2" step="0.05" class="agv-length" value="${length.toFixed(2)}">
                </div>
                <div class="agv-field">
                    <label>Width (m)</label>
                    <input type="number" min="0.2" step="0.05" class="agv-width" value="${width.toFixed(2)}">
                </div>
                <div class="agv-field">
                    <label>Maximum speed (m/s)</label>
                    <input type="number" min="0.1" step="0.1" class="agv-max-speed" value="${maxSpeed.toFixed(2)}">
                </div>
                <div class="agv-field">
                    <label>Position (X, Y)</label>
                    <div class="agv-position">(${agv.position.x.toFixed(2)}, ${agv.position.y.toFixed(2)})</div>
                </div>
                <div class="agv-field" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #eee;">
                    <label style="font-weight: bold; color: #333;">Battery settings</label>
                    <div style="font-size: 11px; color: #666; margin-bottom: 8px;">
                        ${agv.battery_config ? 'Use AGV-specific battery settings' : 'Use global battery settings'}
                    </div>
                    <div style="margin-bottom: 8px;">
                        <label style="font-size: 12px; color: #666;">Charge rate (%/s)</label>
                        <input type="number" min="0" step="0.1" class="agv-battery-charge-rate"
                            value="${agv.battery_config ? agv.battery_config.chargeRate : batteryConfig.chargeRate}"
                            placeholder="${batteryConfig.chargeRate}">
                    </div>
                    <div style="margin-bottom: 8px;">
                        <label style="font-size: 12px; color: #666;">Idle consumption (%/s)</label>
                        <input type="number" min="0" step="0.01" class="agv-battery-idle-consumption"
                            value="${agv.battery_config ? agv.battery_config.idleConsumption : batteryConfig.idleConsumption}"
                            placeholder="${batteryConfig.idleConsumption}">
                    </div>
                    <div style="margin-bottom: 8px;">
                        <label style="font-size: 12px; color: #666;">Working consumption (%/s)</label>
                        <input type="number" min="0" step="0.01" class="agv-battery-working-consumption"
                            value="${agv.battery_config ? agv.battery_config.workingConsumption : batteryConfig.workingConsumption}"
                            placeholder="${batteryConfig.workingConsumption}">
                    </div>
                    <div style="margin-top: 8px;">
                        <label style="font-size: 11px; color: #666;">
                            <input type="checkbox" class="agv-use-custom-battery" ${agv.battery_config ? 'checked' : ''}>
                            Use AGV-specific battery settings (clear to use global settings)
                        </label>
                    </div>
                </div>
                <div class="agv-card-actions">
                    <button type="button" class="btn-small primary" data-action="detail-save">Save</button>
                </div>
            `;
        }

        function getPriorityLabel(priority) {
            const map = {
                low: 'Low',
                medium: 'Medium',
                high: 'High'
            };
            return map[priority] || priority || 'Medium';
        }

        function renderTaskDetailFields(task) {
            const priorityLabel = getPriorityLabel(task.priority);
            const statusLabel = task.status === 'moving_to_dropoff'
                ? formatDropoffProgress(task)
                : getTaskStatusLabel(task.status);
            return `
                <div class="agv-item-detail-header">
                    <strong>${task.name || task.id}</strong>
                    <span class="task-status-pill ${task.status}">${statusLabel}</span>
                </div>
                <div class="agv-field">
                    <label>Task name</label>
                    <input type="text" class="task-name-input" value="${task.name || ''}" placeholder="Enter a task name">
                </div>
                <div class="agv-field">
                    <label>Start vertex</label>
                    <input type="text" class="task-start-vertex" value="${task.start_vertex || ''}" placeholder="Enter start vertex ID">
                </div>
                <div class="agv-field">
                    <label>Destination vertices${task.end_vertices && task.end_vertices.length > 0 ? ` (${task.end_vertices.length} destinations)` : ' (no destinations)'}</label>
                    <div class="task-end-vertices-container">
                        ${(task.end_vertices && task.end_vertices.length > 0 ? task.end_vertices : []).map((endVertex, idx) => `
                            <div class="task-end-vertex-item" style="display: flex; gap: 4px; margin-bottom: 4px;">
                                <span style="min-width:48px;color:#666;font-size:12px;">Destination ${idx + 1}</span>
                                <input type="text" class="task-end-vertex" data-end-index="${idx}" value="${endVertex || ''}" placeholder="Enter destination vertex ID">
                                <button type="button" class="btn-small danger" data-action="remove-end-vertex" data-index="${idx}" style="padding: 2px 8px;">delete</button>
                            </div>
                        `).join('')}
                        <button type="button" class="btn-small secondary" data-action="add-end-vertex" style="margin-top: 4px; padding: 4px 8px;">+ Add destination</button>
                    </div>
                </div>
                <div class="agv-field">
                    <label>Priority</label>
                    <select class="task-priority">
                        <option value="low" ${task.priority === 'low' ? 'selected' : ''}>Low</option>
                        <option value="medium" ${task.priority === 'medium' ? 'selected' : ''}>Medium</option>
                        <option value="high" ${task.priority === 'high' ? 'selected' : ''}>High</option>
                    </select>
                </div>
                <div class="agv-field">
                    <label>Status</label>
                    <select class="task-status">
                        <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Pending</option>
                        <option value="submitted" ${task.status === 'submitted' ? 'selected' : ''}>Submitted</option>
                        <option value="moving_to_pickup" ${task.status === 'moving_to_pickup' ? 'selected' : ''}>Moving to pickup</option>
                        <option value="moving_to_dropoff" ${task.status === 'moving_to_dropoff' ? 'selected' : ''}>Moving to dropoff</option>
                        <option value="completed" ${task.status === 'completed' ? 'selected' : ''}>Completed</option>
                        <option value="failed" ${task.status === 'failed' ? 'selected' : ''}>Failed</option>
                    </select>
                </div>
                <div class="agv-field">
                    <label>Start time (MM:SS)</label>
                    <input type="text" class="task-start-time" value="${task.start_time || ''}" placeholder="Example: 05:30" pattern="[0-9]{1,3}:[0-5][0-9]">
                </div>
                <div class="agv-field">
                    <label>Deadline (MM:SS)</label>
                    <input type="text" class="task-deadline" value="${task.deadline || ''}" placeholder="Example: 10:45" pattern="[0-9]{1,3}:[0-5][0-9]">
                </div>
                <div class="task-meta">ID: ${task.id}</div>
                ${task.status === 'completed' ? `<div class="task-meta">Completed: ${getTaskCompletionTime(task)}</div>` : ''}
                <div class="agv-card-actions">
                    <button type="button" class="btn-small primary" data-action="task-save">Save</button>
                    <button type="button" class="btn-small secondary" data-task-action="delete">delete</button>
                </div>
            `;
        }

        function formatTaskTime(timeStr) {
            if (!timeStr) return 'Not set';

            if (/^\d{1,3}:[0-5][0-9]$/.test(timeStr)) {
                return timeStr;
            }

            const d = new Date(timeStr);
            if (!Number.isNaN(d.getTime())) {
                return d.toLocaleString();
            }
            return timeStr;
        }

        function parseTimeSeconds(timeStr) {
            if (!timeStr) return Infinity;
            if (typeof timeStr === 'number') {
                return Number.isFinite(timeStr) ? timeStr : Infinity;
            }
            const parts = timeStr.split(':');
            if (parts.length === 2) {
                const minutes = parseInt(parts[0], 10);
                const seconds = parseInt(parts[1], 10);
                if (Number.isNaN(minutes) || Number.isNaN(seconds)) {
                    return Infinity;
                }
                return minutes * 60 + seconds;
            }
            return Infinity;
        }

        function getTaskStatusLabel(status) {
            const map = {
                'pending': 'Pending',
                'submitted': 'Submitted',
                'assigned': 'Assigned',
                'moving_to_pickup': 'Moving to pickup',
                'moving_to_dropoff': 'Moving to dropoff',
                'completed': 'Completed',
                'failed': 'Failed'
            };
            return map[status] || status || 'Unknown';
        }

        function getEndVerticesFromTask(task) {
            if (!task) return [];
            if (Array.isArray(task.end_vertices) && task.end_vertices.length) return task.end_vertices;
            if (task.end_vertex) return [task.end_vertex];
            return [];
        }

        function formatDropoffProgress(task) {
            const ends = getEndVerticesFromTask(task);
            const total = ends.length;
            if (total === 0) return 'Moving to dropoff';
            const idx = (task?.current_end_index ?? 0) + 1;
            const safeIdx = Math.min(Math.max(idx, 1), total);
            return `Moving to dropoff ${safeIdx}/${total}`;
        }

        function resetTaskListRenderState() {
            taskListRenderState.listEl = null;
            taskListRenderState.elements.clear();
            taskListRenderState.signatures.clear();
            taskListRenderState.order = [];
            taskListRenderState.dirty = false;
        }

        function getTaskListContainer() {
            return document.getElementById('taskListContent');
        }

        function renderTaskListPlaceholder(message, className = 'task-empty') {
            const container = getTaskListContainer();
            if (!container) return;
            resetTaskListRenderState();
            container.innerHTML = `<div class="${className}">${message}</div>`;
        }

        function getSortedTasksForDisplay() {
            return [...tasks].sort((a, b) => {
                const diff = parseTimeSeconds(a.start_time) - parseTimeSeconds(b.start_time);
                if (diff !== 0) return diff;
                return String(a.id || '').localeCompare(String(b.id || ''));
            });
        }

        function getTaskStatusDisplay(task) {
            return task.status === 'moving_to_dropoff'
                ? formatDropoffProgress(task)
                : getTaskStatusLabel(task.status);
        }

        function buildTaskDataSignature(task) {
            return [
                task.id || '',
                task.name || '',
                task.start_vertex || '',
                getEndVerticesFromTask(task).join('|'),
                task.priority || '',
                task.start_time || '',
                task.deadline || '',
                task.status || '',
                task.created_at || '',
                task.agv_id || '',
                task.completed_at || '',
                task.completed_at_sim ?? '',
                task.current_end_index ?? ''
            ].join('::');
        }

        function buildTaskItemSignature(task, expanded) {
            return [
                buildTaskDataSignature(task),
                expanded ? '1' : '0',
                isTaskOverdue(task) ? '1' : '0',
                task.status === 'completed' ? getTaskCompletionTime(task) : '--'
            ].join('::');
        }

        function renderTaskListItemContent(task, expanded) {
            const startTime = task.start_time || 'Not set';
            const completionDisplay = task.status === 'completed' ? getTaskCompletionTime(task) : '--';
            const detailContent = expanded ? renderTaskDetailFields(task) : '';
            return `
                <div class="task-header">
                    <div class="task-row-top">
                        <span class="task-name">${task.name}</span>
                        <span class="task-status-pill ${task.status}">${getTaskStatusDisplay(task)}</span>
                    </div>
                    <div class="task-time-bar">
                        <div class="task-time-cell">
                            <span>Start</span>
                            <strong>${startTime}</strong>
                        </div>
                        <div class="task-time-cell">
                            <span>End</span>
                            <strong>${task.deadline || '-'}</strong>
                        </div>
                        <div class="task-time-cell">
                            <span>Done</span>
                            <strong>${completionDisplay}</strong>
                        </div>
                    </div>
                </div>
                <div class="task-details ${expanded ? '' : 'hidden'}">
                    ${detailContent}
                </div>
            `;
        }

        function applyTaskListItemState(item, task, expanded) {
            const isOverdueTask = isTaskOverdue(task);
            item.className = ['task-list-item', expanded ? 'active expanded' : '', isOverdueTask ? 'task-overdue' : '']
                .filter(Boolean)
                .join(' ');
            item.dataset.taskId = task.id;
            item.innerHTML = renderTaskListItemContent(task, expanded);
        }

        function ensureTaskListRoot(container) {
            let listEl = taskListRenderState.listEl;
            if (listEl && container.contains(listEl)) {
                return listEl;
            }

            listEl = container.querySelector('.task-list');
            if (!listEl) {
                container.innerHTML = '';
                listEl = document.createElement('div');
                listEl.className = 'task-list';
                container.appendChild(listEl);
            }
            taskListRenderState.listEl = listEl;
            return listEl;
        }

        function syncTaskListDom(sortedTasks) {
            const container = getTaskListContainer();
            if (!container) return;

            const listEl = ensureTaskListRoot(container);
            const nextOrder = [];
            const nextIds = new Set();

            sortedTasks.forEach(task => {
                const taskId = String(task.id);
                const expanded = task.id === selectedTaskId;
                const signature = buildTaskItemSignature(task, expanded);
                let item = taskListRenderState.elements.get(taskId);

                if (!item) {
                    item = document.createElement('div');
                    taskListRenderState.elements.set(taskId, item);
                    applyTaskListItemState(item, task, expanded);
                    taskListRenderState.signatures.set(taskId, signature);
                } else if (taskListRenderState.signatures.get(taskId) !== signature) {
                    applyTaskListItemState(item, task, expanded);
                    taskListRenderState.signatures.set(taskId, signature);
                }

                nextOrder.push(taskId);
                nextIds.add(taskId);
            });

            taskListRenderState.elements.forEach((item, taskId) => {
                if (nextIds.has(taskId)) return;
                item.remove();
                taskListRenderState.elements.delete(taskId);
                taskListRenderState.signatures.delete(taskId);
            });

            const orderChanged = nextOrder.length !== taskListRenderState.order.length
                || nextOrder.some((taskId, index) => taskListRenderState.order[index] !== taskId);

            if (orderChanged) {
                const fragment = document.createDocumentFragment();
                nextOrder.forEach(taskId => {
                    const item = taskListRenderState.elements.get(taskId);
                    if (item) {
                        fragment.appendChild(item);
                    }
                });
                listEl.appendChild(fragment);
            }

            taskListRenderState.order = nextOrder;
            taskListRenderState.dirty = false;
        }

        function haveTasksChanged(nextTasks) {
            if (tasks.length !== nextTasks.length) return true;
            const currentSignatures = new Map(tasks.map(task => [String(task.id), buildTaskDataSignature(task)]));
            for (const task of nextTasks) {
                const taskId = String(task.id);
                if (currentSignatures.get(taskId) !== buildTaskDataSignature(task)) {
                    return true;
                }
                currentSignatures.delete(taskId);
            }
            return currentSignatures.size !== 0;
        }

        function updateTaskCountSummary() {
            const el = document.getElementById('taskCountSummary');
            if (!el) return;
            const total = tasks.length;
            const completed = tasks.filter(t => t.status === 'completed').length;
            el.textContent = `Task ${total} / Completed ${completed}`;
        }

        function updateTaskListPanel(force = false) {
            updateTaskCountSummary();

            if (!force && isUserInteractingWithTaskList) {
                return;
            }

            if (!force && activeDrawerTab !== 'task') {
                taskListRenderState.dirty = true;
                return;
            }

            const container = getTaskListContainer();
            if (!container) return;

            if (!isSceneActive()) {
                renderTaskListPlaceholder('Create or load a scene first');
                return;
            }
            if (tasks.length === 0) {
                renderTaskListPlaceholder('No tasks');
                return;
            }

            syncTaskListDom(getSortedTasksForDisplay());
        }

        function updateAgvList(force = false) {

            if (!force && isUserInteractingWithAgvList) {
                return;
            }

            const list = document.getElementById('agvList');
            if (list) {
                if (!agvListLoaded && !isSceneActive()) {
                    list.innerHTML = `
                        <div class="agv-placeholder">
                            <p>AGV list is not loaded</p>
                            <button type="button" class="btn-small primary" data-action="load-agvs">Load AGV list</button>
                        </div>
                    `;
                } else if (agvs.length === 0) {
                    list.innerHTML = '<div class="agv-empty">No AGVs</div>';
                } else {
                    list.innerHTML = `
                        <div class="agv-list">
                            ${agvs.map(agv => {
                                const statusInfo = getListStatusInfo(agv);
                                const expanded = agv.id === selectedAgvId;
                                return `
                                    <div class="agv-list-item ${expanded ? 'active expanded' : ''}" data-agv-id="${agv.id}">
                                        <div class="agv-list-item-top">
                                            <span class="agv-code">${agv.name || agv.id} (${(agv.battery || 100).toFixed(1)}%)</span>
                                            <span class="status-pill ${statusInfo.className}">${statusInfo.label}</span>
                                        </div>
                                        <div class="agv-item-detail ${expanded ? '' : 'hidden'}">
                                            ${renderAgvDetailFields(agv)}
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    `;
                }
            }

            updateTaskListPanel();
        }

        function setDrawerTab(tabName) {
            activeDrawerTab = tabName;
            const tabs = document.querySelectorAll('#rightDrawer .drawer-tab');
            tabs.forEach(tab => {
                tab.classList.toggle('active', tab.dataset.tab === tabName);
            });
            const agvListEl = document.getElementById('agvList');
            const taskListEl = document.getElementById('taskList');
            if (agvListEl) {
                agvListEl.classList.toggle('hidden', tabName !== 'agv');
            }
            if (taskListEl) {
                taskListEl.classList.toggle('hidden', tabName !== 'task');
            }
            const logListEl = document.getElementById('logList');
            if (logListEl) {
                logListEl.classList.toggle('hidden', tabName !== 'log');
            }
            if (tabName === 'task' && taskListRenderState.dirty) {
                updateTaskListPanel(true);
            }
        }

        const agvListElement = document.getElementById('agvList');
        if (agvListElement) {

            agvListElement.addEventListener('mouseenter', function() {
                isUserInteractingWithAgvList = true;
                if (agvListInteractionTimeout) {
                    clearTimeout(agvListInteractionTimeout);
                }
            });

            agvListElement.addEventListener('mouseleave', function() {

                if (agvListInteractionTimeout) {
                    clearTimeout(agvListInteractionTimeout);
                }
                agvListInteractionTimeout = setTimeout(() => {
                    isUserInteractingWithAgvList = false;
                }, 500);
            });

            agvListElement.addEventListener('click', async function(e) {

                isUserInteractingWithAgvList = true;
                if (agvListInteractionTimeout) {
                    clearTimeout(agvListInteractionTimeout);
                }

                agvListInteractionTimeout = setTimeout(() => {
                    isUserInteractingWithAgvList = false;
                }, 2000);

                const loadBtn = e.target.closest('button[data-action="load-agvs"]');
                if (loadBtn) {
                    await fetchAgvs();
                    return;
                }

                const saveBtn = e.target.closest('button[data-action="detail-save"]');
                if (saveBtn) {
                    const item = saveBtn.closest('.agv-list-item');
                    if (!item) return;
                    const agvId = item.getAttribute('data-agv-id');
                    if (!agvId) return;
                    const status = item.querySelector('.agv-status')?.value || 'idle';
                    const orientation = parseFloat(item.querySelector('.agv-orientation')?.value) || 0;
                    const length = parseFloat(item.querySelector('.agv-length')?.value) || 0.7;
                    const width = parseFloat(item.querySelector('.agv-width')?.value) || 0.5;
                    const maxSpeed = parseFloat(item.querySelector('.agv-max-speed')?.value);
                    const payload = {
                        status,
                        orientation,
                        length,
                        width
                    };
                    if (Number.isFinite(maxSpeed) && maxSpeed > 0) {
                        payload.max_speed = maxSpeed;
                    }


                    const useCustomBattery = item.querySelector('.agv-use-custom-battery')?.checked || false;
                    if (useCustomBattery) {
                        const chargeRate = parseFloat(item.querySelector('.agv-battery-charge-rate')?.value);
                        const idleConsumption = parseFloat(item.querySelector('.agv-battery-idle-consumption')?.value);
                        const workingConsumption = parseFloat(item.querySelector('.agv-battery-working-consumption')?.value);

                        if (Number.isFinite(chargeRate) && Number.isFinite(idleConsumption) && Number.isFinite(workingConsumption)) {
                            payload.battery_config = {
                                chargeRate: chargeRate,
                                idleConsumption: idleConsumption,
                                workingConsumption: workingConsumption
                            };
                        }
                    } else {

                        payload.battery_config = null;
                    }

                    await updateAgvOnServer(agvId, payload, false);
                    return;
                }

                if (e.target.closest('.agv-item-detail')) {
                    return;
                }

                const item = e.target.closest('.agv-list-item');
                if (!item) return;
                const agvId = item.getAttribute('data-agv-id');
                if (!agvId) return;
                selectedAgvId = agvId === selectedAgvId ? null : agvId;
                updateAgvList(true);
                redraw();
            });
        }

        const taskListElement = document.getElementById('taskList');
        if (taskListElement) {

            taskListElement.addEventListener('mouseenter', function() {
                isUserInteractingWithTaskList = true;
                if (taskListInteractionTimeout) {
                    clearTimeout(taskListInteractionTimeout);
                }
            });

            taskListElement.addEventListener('mouseleave', function() {

                if (taskListInteractionTimeout) {
                    clearTimeout(taskListInteractionTimeout);
                }
                taskListInteractionTimeout = setTimeout(() => {
                    isUserInteractingWithTaskList = false;
                }, 500);
            });

            taskListElement.addEventListener('click', async function(e) {

                isUserInteractingWithTaskList = true;
                if (taskListInteractionTimeout) {
                    clearTimeout(taskListInteractionTimeout);
                }

                taskListInteractionTimeout = setTimeout(() => {
                    isUserInteractingWithTaskList = false;
                }, 2000);


                if (e.target.id === 'generateTaskBtn') {
                    if (!currentScene) {
                        alert('Load a scene first');
                        return;
                    }
                    openGenerateTaskModal();
                    return;
                }

                const saveBtn = e.target.closest('button[data-action="task-save"]');
                if (saveBtn) {
                    const taskItem = saveBtn.closest('.task-list-item');
                    if (!taskItem) return;
                    const taskId = taskItem.getAttribute('data-task-id');
                    if (!taskId) return;

                    const task = tasks.find(t => t.id === taskId);
                    if (!task) return;


                    const name = taskItem.querySelector('.task-name-input')?.value?.trim() || task.name || 'Unnamed task';
                    const startVertex = taskItem.querySelector('.task-start-vertex')?.value?.trim() || '';

                    const endVertexInputs = taskItem.querySelectorAll('.task-end-vertex');
                    const endVertices = Array.from(endVertexInputs)
                        .map(input => input.value?.trim() || '')
                        .filter(v => v);

                    const priority = taskItem.querySelector('.task-priority')?.value || 'medium';
                    const status = taskItem.querySelector('.task-status')?.value || 'pending';
                    const startTime = taskItem.querySelector('.task-start-time')?.value?.trim() || null;
                    const deadline = taskItem.querySelector('.task-deadline')?.value?.trim() || null;


                    task.name = name;
                    task.start_vertex = startVertex;

                    if (endVertices.length > 0) {
                        task.end_vertices = endVertices;
                        task.end_vertex = endVertices[0];
                    } else {
                        task.end_vertices = [];
                        task.end_vertex = '';
                    }
                    task.priority = priority;
                    task.status = status;
                    task.start_time = startTime;
                    task.deadline = deadline;


                    highlightedTaskVertices = {
                        start: startVertex || null,
                        end: endVertices.length > 0 ? endVertices[0] : null,
                        end_vertices: endVertices
                    };


                    await persistSceneData();
                    updateTaskListPanel(true);
                    redraw();
                    updateInfo(`Task ${name} updated`);
                    return;
                }

                const deleteBtn = e.target.closest('button[data-task-action="delete"]');
                if (deleteBtn) {
                    const taskItem = deleteBtn.closest('.task-list-item');
                    if (!taskItem) return;
                    const taskId = taskItem.getAttribute('data-task-id');
                    tasks = tasks.filter(task => task.id !== taskId);
                    updateTaskListPanel(true);

                    return;
                }


                const addEndVertexBtn = e.target.closest('button[data-action="add-end-vertex"]');
                if (addEndVertexBtn) {
                    const taskItem = addEndVertexBtn.closest('.task-list-item');
                    if (!taskItem) return;
                    const container = taskItem.querySelector('.task-end-vertices-container');
                    if (!container) return;

                    const newIndex = container.querySelectorAll('.task-end-vertex-item').length;
                    const newItem = document.createElement('div');
                    newItem.className = 'task-end-vertex-item';
                    newItem.style.cssText = 'display: flex; gap: 4px; margin-bottom: 4px;';
                    newItem.innerHTML = `
                        <input type="text" class="task-end-vertex" data-end-index="${newIndex}" value="" placeholder="Enter destination vertex ID">
                        <button type="button" class="btn-small danger" data-action="remove-end-vertex" data-index="${newIndex}" style="padding: 2px 8px;">delete</button>
                    `;
                    const addBtn = container.querySelector('button[data-action="add-end-vertex"]');
                    container.insertBefore(newItem, addBtn);
                    return;
                }


                const removeEndVertexBtn = e.target.closest('button[data-action="remove-end-vertex"]');
                if (removeEndVertexBtn) {
                    const taskItem = removeEndVertexBtn.closest('.task-list-item');
                    if (!taskItem) return;
                    const itemToRemove = removeEndVertexBtn.closest('.task-end-vertex-item');
                    if (!itemToRemove) return;


                    const allItems = taskItem.querySelectorAll('.task-end-vertex-item');
                    if (allItems.length <= 1) {

                        const input = itemToRemove.querySelector('.task-end-vertex');
                        if (input) input.value = '';
                        return;
                    }

                    itemToRemove.remove();

                    const remainingItems = taskItem.querySelectorAll('.task-end-vertex-item');
                    remainingItems.forEach((item, idx) => {
                        const input = item.querySelector('.task-end-vertex');
                        const label = item.querySelector('span');
                        const removeBtn = item.querySelector('button[data-action="remove-end-vertex"]');
                        if (input) {
                            input.setAttribute('data-end-index', idx);
                        }
                        if (label) {
                            label.textContent = `Destination ${idx + 1}`;
                        }
                        if (removeBtn) {
                            removeBtn.setAttribute('data-index', idx);
                        }
                    });
                    return;
                }


                if (e.target.closest('.task-details')) {
                    return;
                }


                const header = e.target.closest('.task-header');
                if (header) {
                    const taskItem = header.closest('.task-list-item');
                    const taskId = taskItem.getAttribute('data-task-id');
                    const wasSelected = selectedTaskId === taskId;
                    selectedTaskId = wasSelected ? null : taskId;


                    if (selectedTaskId) {
                        const task = tasks.find(t => t.id === selectedTaskId);
                        if (task) {
                            const endVertices = task.end_vertices && task.end_vertices.length > 0
                                ? task.end_vertices
                                : (task.end_vertex ? [task.end_vertex] : []);
                            highlightedTaskVertices = {
                                start: task.start_vertex || null,
                                end: endVertices.length > 0 ? endVertices[0] : null,
                                end_vertices: endVertices
                            };
                        }
                    } else {
                        highlightedTaskVertices = { start: null, end: null, end_vertices: [] };
                    }

                    updateTaskListPanel(true);
                    redraw();
                }
            });
        }

        const drawerTabsElement = document.querySelector('#rightDrawer .drawer-tabs');
        if (drawerTabsElement) {
            drawerTabsElement.addEventListener('click', function(e) {
                const tabButton = e.target.closest('.drawer-tab');
                if (!tabButton) return;
                const targetTab = tabButton.dataset.tab;
                if (!targetTab || targetTab === activeDrawerTab) return;
                setDrawerTab(targetTab);
            });
            setDrawerTab(activeDrawerTab);
        }



        function loadMap(mapKey) {
            if (!mapKey) {
                console.warn('No map key specified');
                return;
            }
            const data = mapData[mapKey];
            if (!data) {
                console.warn(`Map ${mapKey} is missing from mapData; waiting for the scene`);
                updateInfo('Map configuration is not loaded; load a scene first');
                return;
            }

            updateInfo(`Loading map: ${mapKey} floor`);

            mapImage = new Image();
            mapImage.onload = function() {
                mapPixelWidth = this.width;
                mapPixelHeight = this.height;
                resizeCanvas();
                updateInfo('Map loaded');
            };
            mapImage.onerror = function() {
                updateInfo('Failed to load map');
            };
            mapImage.src = data.image;
        }




        async function loadServerConfig() {
            try {
                const response = await fetch(`${API_BASE}/config`);
                const result = await response.json();
                if (result.success && result.config.map) {

                    Object.assign(mapData, result.config.map);
                    console.log('Map configuration loaded from the server');
                }
            } catch (error) {
                console.log('Using default configuration');
            }
        }



        async function restoreAppState() {
            try {
                const response = await fetch(`${API_BASE}/app/state`);
                const result = await response.json();
                if (result.success && result.state && result.state.active_scene) {
                    const state = result.state;
                    console.log('Restoring application state:', state);

                    // Load sceneData
                    const sceneResp = await fetch(`${API_BASE}/scenes/${encodeURIComponent(state.active_scene)}`);
                    const sceneResult = await sceneResp.json();

                    if (sceneResult.success) {

                        await applySceneData(sceneResult.scene);
                        updateInfo(`Scene restored: ${state.active_scene}`);

                        // Resume simulationStatus
                        simRunning = !!state.is_simulation_running;
                        simPaused = !!state.is_simulation_paused;
                        simSpeed = state.simulation_speed || 1.0;
                        simTime = state.current_sim_time || 0;


                        updateSimControls();


                        if (simRunning) {
                            startSimPolling(simTime);
                        } else {
                            pollAgvStates();
                        }
                    }
                }
            } catch (e) {
                console.error('Failed to restore application state:', e);
            }
        }

        async function initApp() {

            await loadServerConfig();


            await restoreAppState();

            setupActionConfigUI();
            setupBatteryConfigUI();
            setupDrawers();

            if (currentMap) {
                loadMap(currentMap);
            } else {
                const mapKeys = Object.keys(mapData);
                if (mapKeys.length > 0) {
                    currentMap = mapKeys[0];
                    loadMap(currentMap);
                } else {
                    console.warn('No map configuration loaded; waiting for a scene');
                    updateInfo('Load a scene to load its map');
                }
            }
            updateInfo('AGV simulator ready');
            updateToolbarState();
            updateSceneIndicator();
            updateAgvList();
            refreshSceneOptions();
            initSimControls();
        }

        // ==================== Simulation controls ====================

        let simRunning = false;
        let simPaused = false;
        let simTime = 0; // seconds
        let simSpeed = 1.0;
        let appStatePollTimer = null;
        let pathPollTimer = null;
        let agvPollTimer = null;
        let logPollTimer = null;
        let taskPollTimer = null; // Fix: Define missing timer
        let lastServerUpdate = 0;
        let simSpeedSyncTimer = null;
        let pendingSimSpeed = null;


        let isUserInteractingWithAgvList = false;
        let isUserInteractingWithTaskList = false;
        let agvListInteractionTimeout = null;
        let taskListInteractionTimeout = null;


        async function syncSimStateFromBackend() {
            if (!currentScene) return;
            try {
                const response = await fetch(`${API_BASE}/app/state`);
                const result = await response.json();
                if (result.success && result.state) {
                    const state = result.state;
                    if (typeof state.current_sim_time === 'number') {
                        simTime = state.current_sim_time;
                    }
                    if (typeof state.is_simulation_paused === 'boolean') {
                        simPaused = state.is_simulation_paused;
                    }
                    if (typeof state.simulation_speed === 'number') {
                        const backendSpeed = state.simulation_speed;
                        if (pendingSimSpeed === null || Math.abs(backendSpeed - pendingSimSpeed) < 0.001) {
                            simSpeed = backendSpeed;
                            if (pendingSimSpeed !== null && Math.abs(backendSpeed - pendingSimSpeed) < 0.001) {
                                pendingSimSpeed = null;
                            }
                        }
                    }
                    if (typeof state.is_simulation_running === 'boolean') {
                        simRunning = state.is_simulation_running;
                    }
                    updateSimDisplay();

                    const startBtn = document.getElementById('startSimBtn');
                    const stopBtn = document.getElementById('stopSimBtn');
                    const pauseBtn = document.getElementById('pauseSimBtn');
                    const speedVal = document.getElementById('simSpeedVal');
                    if (startBtn) startBtn.disabled = !currentScene || simRunning;
                    if (stopBtn) stopBtn.disabled = !simRunning;
                    if (pauseBtn) {
                        pauseBtn.disabled = !simRunning;
                        pauseBtn.textContent = simPaused ? 'Resume' : 'Pause';
                    }
                    if (speedVal) {
                        speedVal.textContent = simSpeed.toFixed(1);
                    }
                }
            } catch (e) {
                console.warn('Failed to synchronize simulation state', e);
            }
        }

        function formatSimTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        function coerceSecondsValue(value) {
            if (typeof value === 'number' && !Number.isNaN(value)) {
                return value;
            }
            if (typeof value === 'string' && value.trim() !== '') {
                const parsed = parseFloat(value);
                if (!Number.isNaN(parsed)) {
                    return parsed;
                }
            }
            return null;
        }

        function formatSimSeconds(seconds) {
            if (seconds === undefined || seconds === null || Number.isNaN(seconds)) {
                return 'Incomplete';
            }
            const total = Math.max(0, Math.floor(seconds));
            const m = Math.floor(total / 60);
            const s = total % 60;
            return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        function getTaskCompletionTime(task) {
            if (!task) return 'Incomplete';
            const simSeconds = coerceSecondsValue(task.completed_at_sim);
            if (simSeconds !== null) {
                return formatSimSeconds(simSeconds);
            }
            if (task.completed_at) {
                return formatTaskTime(task.completed_at);
            }
            return 'Incomplete';
        }

        function isTaskOverdue(task) {
            if (!task || task.status !== 'completed') return false;
            const completedSeconds = coerceSecondsValue(task.completed_at_sim);
            if (completedSeconds === null) return false;
            const deadlineSeconds = parseTimeSeconds(task.deadline);
            if (!Number.isFinite(deadlineSeconds) || deadlineSeconds === Infinity) return false;
            return completedSeconds > deadlineSeconds;
        }

        function updateSimDisplay() {
            const display = document.getElementById('simTimeDisplay');
            if (display) {
                display.textContent = formatSimTime(simTime);
            }
        }

        function updateSimControls() {
            const startBtn = document.getElementById('startSimBtn');
            const stopBtn = document.getElementById('stopSimBtn');
            const pauseBtn = document.getElementById('pauseSimBtn');
            const speedInput = document.getElementById('simSpeed');
            const speedVal = document.getElementById('simSpeedVal');

            if (startBtn) {
                startBtn.disabled = !currentScene || simRunning;
            }
            if (stopBtn) {
                stopBtn.disabled = !simRunning;
            }
            if (pauseBtn) {
                pauseBtn.disabled = !simRunning;
                pauseBtn.textContent = simPaused ? 'Resume' : 'Pause';
            }
            if (speedInput) {
                speedInput.value = simSpeed;
            }
            if (speedVal) {
                speedVal.textContent = simSpeed.toFixed(1);
            }

            updateSimDisplay();
        }

        function scheduleSimSpeedSync(immediate = false) {
            if (!currentScene) return;
            const speedToSend = simSpeed;
            pendingSimSpeed = speedToSend;
            const send = async () => {
                simSpeedSyncTimer = null;
                try {
                    const response = await fetch(`${API_BASE}/simulation/speed`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            scene_name: currentScene,
                            speed: speedToSend
                        })
                    });
                    const result = await response.json();
                    if (result.success && typeof result.speed === 'number') {
                        simSpeed = result.speed;
                    }
                    if (pendingSimSpeed !== null && Math.abs(pendingSimSpeed - speedToSend) < 0.001) {
                        pendingSimSpeed = null;
                    }
                } catch (err) {
                    if (pendingSimSpeed !== null && Math.abs(pendingSimSpeed - speedToSend) < 0.001) {
                        pendingSimSpeed = null;
                    }
                    console.error('Failed to update simulation speed:', err);
                }
            };
            if (immediate) {
                send();
                return;
            }
            if (simSpeedSyncTimer) {
                clearTimeout(simSpeedSyncTimer);
            }
            simSpeedSyncTimer = setTimeout(send, 200);
        }

        function initSimControls() {
            const startBtn = document.getElementById('startSimBtn');
            const stopBtn = document.getElementById('stopSimBtn');
            const pauseBtn = document.getElementById('pauseSimBtn');
            const speedInput = document.getElementById('simSpeed');
            const speedVal = document.getElementById('simSpeedVal');

            if (startBtn) startBtn.onclick = startSimulation;
            if (stopBtn) stopBtn.onclick = stopSimulation;
            if (pauseBtn) pauseBtn.onclick = toggleSimulationPause;

            if (speedInput) {
                speedInput.oninput = function() {
                    simSpeed = parseFloat(this.value);
                    if (speedVal) speedVal.textContent = simSpeed.toFixed(1);
                    scheduleSimSpeedSync();
                };
            }

            const statsBtn = document.getElementById('statsBtn');
            if (statsBtn) {
                statsBtn.onclick = async function() {
                    if (!currentScene) {
                        alert('Load a scene first');
                        return;
                    }
                    const modal = document.getElementById('statsModal');
                    const content = document.getElementById('statsContent');
                    if (modal) modal.style.display = 'block';
                    if (content) content.textContent = 'Loading...';

                    const formatPercent = (value) => {
                        if (!Number.isFinite(value)) return '0.0%';
                        return `${value.toFixed(1)}%`;
                    };
                    const formatSeconds = (value) => {
                        if (!Number.isFinite(value) || value === 0) return '--';
                        return `${value.toFixed(1)}s`;
                    };
                    const buildTable = (items) => {
                        const rows = [];
                        for (let i = 0; i < items.length; i += 2) {
                            rows.push(items.slice(i, i + 2));
                        }
                        return `
                            <table class="stats-table">
                                <tbody>
                                    ${rows.map(row => {
                                        const cells = row.map(item => {
                                            if (!item) {
                                                return '<th></th><td></td>';
                                            }
                                            return `<th>${item.label}</th><td>${item.value}</td>`;
                                        }).join('');
                                        if (row.length === 1) {
                                            return `<tr>${cells}<th></th><td></td></tr>`;
                                        }
                                        return `<tr>${cells}</tr>`;
                                    }).join('')}
                                </tbody>
                            </table>
                        `;
                    };

                    try {
                        const response = await fetch(`/api/simulation/stats?scene_name=${currentScene}`);
                        const result = await response.json();
                        if (result.success && content) {
                            const stats = result.stats || {};
                            const taskStats = stats.tasks || {};
                            const timing = stats.timing || {};
                            const overdue = timing.overdue || {};
                            const early = timing.early || {};

                            const taskItems = [
                                { label: 'Total tasks', value: taskStats.total ?? 0 },
                                { label: 'Completed', value: taskStats.completed ?? 0 },
                                { label: 'Failed', value: taskStats.failed ?? 0 },
                                { label: 'Pending', value: taskStats.pending ?? 0 },
                                { label: 'Driving', value: taskStats.running ?? 0 },
                                { label: 'Success rate', value: formatPercent(taskStats.success_rate) },
                                { label: 'Failure rate', value: formatPercent(taskStats.failure_rate) }
                            ];

                            const overdueItems = [
                                { label: 'Late count', value: overdue.count ?? 0 },
                                { label: 'Share', value: formatPercent(overdue.rate) },
                                { label: 'Average', value: formatSeconds(overdue.avg) },
                                { label: 'Maximum', value: formatSeconds(overdue.max) },
                                { label: 'Minimum', value: formatSeconds(overdue.min) }
                            ];

                            const earlyItems = [
                                { label: 'Early count', value: early.count ?? 0 },
                                { label: 'Share', value: formatPercent(early.rate) },
                                { label: 'Average', value: formatSeconds(early.avg) },
                                { label: 'Maximum', value: formatSeconds(early.max) },
                                { label: 'Minimum', value: formatSeconds(early.min) }
                            ];

                            content.innerHTML = `
                                <div class="stats-section">
                                    <h4>Task overview</h4>
                                    ${buildTable(taskItems)}
                                </div>
                                <div class="stats-section">
                                    <h4>Late tasks</h4>
                                    ${buildTable(overdueItems)}
                                </div>
                                <div class="stats-section">
                                    <h4>Early tasks</h4>
                                    ${buildTable(earlyItems)}
                                </div>
                            `;
                        } else if (content) {
                            content.textContent = `Statistics failed: ${result.error || 'unknown error'}`;
                        }
                    } catch (e) {
                        console.error('Failed to get statistics', e);
                        if (content) content.textContent = 'Failed to get statistics; check the backend log';
                    }
                };
            }


            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState === 'visible' && simRunning && currentScene) {
                    syncSimStateFromBackend();
                    pollAgvStates();
                    pollSimPaths();
                    pollTasks();
                }
            });
        }

        async function pollTasks() {
            if (!simRunning || !currentScene) return;
            try {
                const response = await fetch(`${API_BASE}/scenes/${currentScene}`);
                const result = await response.json();
                if (result.success && result.scene && Array.isArray(result.scene.tasks)) {
                    const serverTasks = result.scene.tasks.map(normalizeTask).filter(Boolean);
                    if (haveTasksChanged(serverTasks)) {
                        tasks = serverTasks;
                        updateTaskListPanel();
                    }
                }
            } catch (err) {
                console.error('Poll Tasks Error:', err);
            }
        }

        function startSimulation() {
            if (!currentScene) {
                alert('Load a scene first');
                return;
            }


            if (!agvListLoaded || agvs.length === 0) {
                console.warn('AGV list not loaded; retrying');
                fetchAgvs().then(() => {
                    if (agvs.length === 0) {
                        alert('The current scene has no AGV');
                    } else {
                         _startSimInternal();
                    }
                });
            } else {
                _startSimInternal();
            }
        }


        function startSimPolling(initialTime) {
            simRunning = true;

            simTime = initialTime || 0;

            document.getElementById('startSimBtn').disabled = true;
            document.getElementById('stopSimBtn').disabled = false;

            const pauseBtn = document.getElementById('pauseSimBtn');
            if (pauseBtn) {
                pauseBtn.disabled = false;
                pauseBtn.textContent = simPaused ? 'Resume' : 'Pause';
            }

            // Show simulation time display
            const timeDisplay = document.getElementById('simTimeDisplay');
            if (timeDisplay) {
                timeDisplay.classList.add('visible');
            }

            if (appStatePollTimer) clearInterval(appStatePollTimer);
            appStatePollTimer = setInterval(syncSimStateFromBackend, 200);
            syncSimStateFromBackend();

            // Start polling paths
            if (pathPollTimer) clearInterval(pathPollTimer);
            pathPollTimer = setInterval(pollSimPaths, 1000);

            // Start polling AGV states
            if (agvPollTimer) clearInterval(agvPollTimer);
            agvPollTimer = setInterval(pollAgvStates, 200);

            // Start polling logs
            if (logPollTimer) clearInterval(logPollTimer);
            logPollTimer = setInterval(pollLogs, 2000);

            // Start polling tasks
            if (taskPollTimer) clearInterval(taskPollTimer);
            taskPollTimer = setInterval(pollTasks, 1000);
            pollTasks();
        }

        function _startSimInternal() {
            // Activate simulation on backend
            if (currentScene) {
                fetch(`${API_BASE}/simulation/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scene_name: currentScene, speed: simSpeed })
                }).catch(err => console.error('Failed to start backend simulation:', err));
            }

            simRunning = true;
            simPaused = false;
            simTime = 0;

            document.getElementById('startSimBtn').disabled = true;
            document.getElementById('stopSimBtn').disabled = false;

            const pauseBtn = document.getElementById('pauseSimBtn');
            if (pauseBtn) {
                pauseBtn.disabled = false;
                pauseBtn.textContent = 'Pause';
            }

            // Show simulation time display
            const timeDisplay = document.getElementById('simTimeDisplay');
            if (timeDisplay) {
                timeDisplay.classList.add('visible');
            }

            if (appStatePollTimer) clearInterval(appStatePollTimer);
            appStatePollTimer = setInterval(syncSimStateFromBackend, 200);
            syncSimStateFromBackend();

            // Start polling paths
            if (pathPollTimer) clearInterval(pathPollTimer);
            pathPollTimer = setInterval(pollSimPaths, 1000);

            // Start polling AGV states (New: driven by backend)

            if (agvPollTimer) clearInterval(agvPollTimer);
            agvPollTimer = setInterval(pollAgvStates, 200);

            // Start polling logs
            if (logPollTimer) clearInterval(logPollTimer);
            logPollTimer = setInterval(pollLogs, 2000);

            // Start polling tasks
            if (taskPollTimer) clearInterval(taskPollTimer);
            taskPollTimer = setInterval(pollTasks, 1000);
            pollTasks();

            updateInfo('Simulation started');
        }

        async function stopSimulation() {
            simRunning = false;
            simPaused = false;
            document.getElementById('startSimBtn').disabled = false;
            document.getElementById('stopSimBtn').disabled = true;

            const pauseBtn = document.getElementById('pauseSimBtn');
            if (pauseBtn) {
                pauseBtn.disabled = true;
                pauseBtn.textContent = 'Pause';
            }

            if (appStatePollTimer) clearInterval(appStatePollTimer);
            if (pathPollTimer) clearInterval(pathPollTimer);
            if (agvPollTimer) clearInterval(agvPollTimer);
            if (logPollTimer) clearInterval(logPollTimer);
            if (taskPollTimer) clearInterval(taskPollTimer);

            // Reset sim time display and hide it
            simTime = 0;
            updateSimDisplay();
            const timeDisplay = document.getElementById('simTimeDisplay');
            if (timeDisplay) {
                timeDisplay.classList.remove('visible');
            }


            if (currentScene) {
                try {
                    const response = await fetch(`${API_BASE}/simulation/reset`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scene_name: currentScene })
                    });
                    const result = await response.json();
                    if (result.success) {

                        const sceneResponse = await fetch(`${API_BASE}/scenes/${currentScene}`);
                        const sceneResult = await sceneResponse.json();
                        if (sceneResult.success) {
                            await applySceneData(sceneResult.scene);
                        }
                    }
                } catch (e) {
                    console.error('Failed to reset scene:', e);
                }
            }

            updateInfo('Simulation stopped; scene reset');
        }

        async function toggleSimulationPause() {
            if (!simRunning) return;

            const pauseBtn = document.getElementById('pauseSimBtn');
            simPaused = !simPaused;

            if (simPaused) {
                // Pause
                if (pauseBtn) pauseBtn.textContent = 'Resume';
                updateInfo('Simulation paused');

                // Notify backend
                if (currentScene) {
                     fetch(`${API_BASE}/simulation/pause`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scene_name: currentScene })
                    }).catch(console.error);
                }

            } else {
                // Resume
                if (pauseBtn) pauseBtn.textContent = 'Pause';
                updateInfo('Simulation resumed');

                // Notify backend
                if (currentScene) {
                     fetch(`${API_BASE}/simulation/resume`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scene_name: currentScene, speed: simSpeed })
                    }).catch(console.error);
                }
            }
        }

        function moveAgvs(dt) {
            const now = Date.now();
            const shouldSync = (now - lastServerUpdate) > 500; // Sync every 500ms

            agvs.forEach(agv => {
                if (!agv.assignedPath || agv.assignedPath.length === 0) return;
                if (!agv.simState) agv.simState = { edgeIdx: 0, dist: 0, finished: false };
                if (agv.simState.finished) return;

                const pathSegment = agv.assignedPath[agv.simState.edgeIdx];
                const edgeId = pathSegment.id || pathSegment; // Handle object or string
                const edge = edgeMap[edgeId];
                if (!edge) {
                    // Edge not found? Skip
                    return;
                }


                const agvSpeedLimit = getAgvMaxSpeed(agv);
                const edgeSpeedLimit = parseFloat(edge.max_speed) || 1.0;
                const speed = Math.max(0, Math.min(agvSpeedLimit, edgeSpeedLimit));
                const moveDist = speed * dt;
                agv.simState.dist += moveDist;

                const len = edge.length || 1.0;

                // Handle edge completion
                if (agv.simState.dist >= len) {
                    agv.simState.dist -= len;
                    agv.simState.edgeIdx++;
                    if (agv.simState.edgeIdx >= agv.assignedPath.length) {
                        agv.simState.finished = true;
                        agv.simState.dist = len; // Clamp
                        agv.simState.edgeIdx = agv.assignedPath.length - 1;
                    }
                }

                // Calculate position
                // Re-fetch edge (index might have changed)
                const currentSegment = agv.assignedPath[agv.simState.edgeIdx];
                const currentEdgeId = currentSegment.id || currentSegment;
                const currentEdge = edgeMap[currentEdgeId];

                if (currentEdge) {
                     // Determine source and target vertices for interpolation
                     let v1, v2;
                     if (typeof currentSegment === 'object' && currentSegment.source && currentSegment.target) {
                         // Directed segment from A*
                         v1 = vertexMap[currentSegment.source];
                         v2 = vertexMap[currentSegment.target];
                     } else {
                         // Fallback or undirected
                         v1 = vertexMap[currentEdge.from];
                         v2 = vertexMap[currentEdge.to];
                     }

                     if (v1 && v2) {
                         const t = Math.min(1, Math.max(0, agv.simState.dist / (currentEdge.length || 1)));
                         agv.position.x = v1.x + (v2.x - v1.x) * t;
                         agv.position.y = v1.y + (v2.y - v1.y) * t;
                         agv.position.z = v1.z;
                     }
                }

                if (shouldSync) {
                    updateAgvOnServer(agv.id, { position: agv.position }, false);
                }
            });

            if (shouldSync) lastServerUpdate = now;

            // Force redraw
            redraw();
        }

        async function pollSimPaths() {
            try {
                // Only poll if simulation is running or we expect updates
                if (!simRunning) return;

                const response = await fetch(`${API_BASE}/simulation/paths`);
                const result = await response.json();
                if (result.success && result.paths) {
                    let pathUpdated = false;
                    for (const [agvId, pathEdges] of Object.entries(result.paths)) {
                        const agv = agvs.find(a => a.id === agvId);
                        if (agv) {
                            // Generate signature
                            const newSig = JSON.stringify(pathEdges);
                            if (agv.pathSignature !== newSig) {
                                agv.assignedPath = pathEdges;
                                agv.pathSignature = newSig;



                                if (!agv.simState || agv.assignedPath.length === 0) {
                                    agv.simState = { edgeIdx: 0, dist: 0, finished: false };
                                }
                                pathUpdated = true;
                            }
                        }
                    }

                    if (pathUpdated) {
                        redraw();
                    }
                }
            } catch (e) {
                console.error('Poll paths error:', e);
            }
        }

        async function pollAgvStates() {
            try {
                if (!simRunning) return;
                const response = await fetch(`${API_BASE}/agvs`);
                const result = await response.json();
                if (result.success && result.agvs) {
                    result.agvs.forEach(serverAgv => {
                        // Update local AGV state directly from server
                        upsertAgv(serverAgv);
                    });
                    updateAgvList(); // Update UI list
                    redraw(); // Redraw canvas
                }
            } catch (e) {
                console.error('Poll AGV Error:', e);
            }
        }

        async function pollLogs() {
            try {

                if (!simRunning || simPaused) return;

                const response = await fetch(`${API_BASE}/logs?limit=200`);
                const result = await response.json();
                if (result.success && result.logs) {
                    updateLogPanel(result.logs);
                }
            } catch (e) {
                console.error('Poll Logs Error:', e);
            }
        }

        function updateLogPanel(logs) {
            const container = document.getElementById('logListContent');
            if (!container) return;
            container.innerHTML = logs.map(log => `
                <div class="log-entry" style="font-family: monospace; font-size: 12px; border-bottom: 1px solid #eee; padding: 2px;">
                    <span style="color: #888;">[${log.timestamp.split('T')[1].split('.')[0]}]</span>
                    <span style="font-weight: bold; color: ${log.level === 'ERROR' ? 'red' : 'blue'};">${log.level}</span>
                    <span>${log.message}</span>
                </div>
            `).join('');
            container.scrollTop = container.scrollHeight;
        }

        Object.assign(window, {
            closeSavePathModal,
            confirmSavePath,
            closeCreateAgvModal,
            confirmCreateAgv,
            closeTaskModal,
            closeSceneModal,
            closeGenerateTaskModal,
            closeHelpPanel
        });

        // Battery Config UI Logic
        function setupBatteryConfigUI() {
            const btn = document.getElementById('batteryConfigBtn');
            const modal = document.getElementById('batteryConfigModal');
            const confirmBtn = document.getElementById('confirmBatteryConfigBtn');

            if (!btn || !modal) return;

            btn.addEventListener('click', () => {
                document.getElementById('chargeRateInput').value = batteryConfig.chargeRate;
                document.getElementById('idleConsumptionInput').value = batteryConfig.idleConsumption;
                document.getElementById('workingConsumptionInput').value = batteryConfig.workingConsumption;
                modal.style.display = 'block';
            });

            confirmBtn.addEventListener('click', () => {
                batteryConfig.chargeRate = parseFloat(document.getElementById('chargeRateInput').value) || 1.0;
                batteryConfig.idleConsumption = parseFloat(document.getElementById('idleConsumptionInput').value) || 0.1;
                batteryConfig.workingConsumption = parseFloat(document.getElementById('workingConsumptionInput').value) || 0.5;
                modal.style.display = 'none';
                updateInfo('Battery settings updated');
            });
        }

        // Action Config UI Logic
        function setupActionConfigUI() {
            const btn = document.getElementById('actionConfigBtn');
            const modal = document.getElementById('actionConfigModal');
            const confirmBtn = document.getElementById('confirmActionConfigBtn');
            const listContainer = document.getElementById('actionConfigList');

            if (!btn || !modal) return;

            btn.addEventListener('click', () => {
                renderActionConfigList();
                modal.style.display = 'block';
            });

            confirmBtn.addEventListener('click', () => {
                saveActionConfigs();
                modal.style.display = 'none';
            });

            function renderActionConfigList() {
                listContainer.innerHTML = '';

                const actions = Object.keys(actionConfigs);
                if (actions.length === 0) {
                    listContainer.innerHTML = '<div style="text-align:center; color:#888;">No action settings</div>';
                    return;
                }

                actions.forEach(action => {
                    const config = actionConfigs[action];
                    const row = document.createElement('div');
                    row.className = 'config-row';
                    row.style.cssText = 'display: flex; align-items: center; padding: 5px; border-bottom: 1px solid #eee; margin-bottom: 5px;';

                    const nameCol = document.createElement('div');
                    nameCol.style.flex = '1';
                    nameCol.textContent = action;

                    const typeCol = document.createElement('div');
                    typeCol.style.flex = '1';
                    const typeSelect = document.createElement('select');
                    typeSelect.innerHTML = `
                        <option value="fixed" ${config.type === 'fixed' ? 'selected' : ''}>Fixed duration</option>
                        <option value="random" ${config.type === 'random' ? 'selected' : ''}>Random duration</option>
                    `;

                    const paramsCol = document.createElement('div');
                    paramsCol.style.flex = '2';
                    renderParams(paramsCol, config.type, config);

                    typeSelect.onchange = () => renderParams(paramsCol, typeSelect.value, config);
                    typeCol.appendChild(typeSelect);

                    row.appendChild(nameCol);
                    row.appendChild(typeCol);
                    row.appendChild(paramsCol);
                    listContainer.appendChild(row);

                    // Store references for saving
                    row.dataset.action = action;
                });
            }

            function renderParams(container, type, currentConfig) {
                container.innerHTML = '';
                if (type === 'fixed') {
                    const val = (currentConfig.type === 'fixed' && currentConfig.value !== undefined) ? currentConfig.value : 5;
                    container.innerHTML = `
                        <input type="number" class="param-value" value="${val}" min="0" step="0.1" style="width: 80px;"> s
                    `;
                } else {
                    const min = (currentConfig.type === 'random' && currentConfig.min !== undefined) ? currentConfig.min : 2;
                    const max = (currentConfig.type === 'random' && currentConfig.max !== undefined) ? currentConfig.max : 10;
                    container.innerHTML = `
                        <input type="number" class="param-min" value="${min}" min="0" step="0.1" style="width: 60px;"> -
                        <input type="number" class="param-max" value="${max}" min="0" step="0.1" style="width: 60px;"> s
                    `;
                }
            }

            function saveActionConfigs() {
                const rows = listContainer.querySelectorAll('.config-row');
                const newConfigs = {};
                rows.forEach(row => {
                    const action = row.dataset.action;
                    const type = row.querySelector('select').value;

                    if (type === 'fixed') {
                        const val = parseFloat(row.querySelector('.param-value').value) || 0;
                        newConfigs[action] = { type: 'fixed', value: val };
                    } else {
                        const min = parseFloat(row.querySelector('.param-min').value) || 0;
                        const max = parseFloat(row.querySelector('.param-max').value) || 0;
                        newConfigs[action] = { type: 'random', min, max };
                    }
                });
                // Keep existing configs that were not in the list (unlikely but safe)
                actionConfigs = { ...actionConfigs, ...newConfigs };
                updateInfo('Action timing updated');
            }
        }


        function setupDrawers() {
            const leftDrawer = document.getElementById('leftDrawer');
            const rightDrawer = document.getElementById('rightDrawer');

            if (leftDrawer) {
                const handle = leftDrawer.querySelector('.drawer-handle');
                if (handle) {
                    handle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        leftDrawer.classList.toggle('open');
                    });
                }
            }

            if (rightDrawer) {
                const handle = rightDrawer.querySelector('.drawer-handle');
                if (handle) {
                    handle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        rightDrawer.classList.toggle('open');
                    });
                }
            }


            //document.addEventListener('click', (e) => {
            //    const inDrawer = e.target.closest && e.target.closest('.drawer');
            //    if (inDrawer) return;
            //    if (leftDrawer) leftDrawer.classList.remove('open');
            //    if (rightDrawer) rightDrawer.classList.remove('open');
            //});
        }
