import heapq
import math

class ParkingRouter:
    """
    A* / Dijkstra Pathfinding Engine for Multi-Floor Parking Facility (Floor 1 + Floor 2, 56 Bays).
    Supports orthogonal rectilinear aisle routing and seamless inter-floor ramp transitions
    (SLOPE UP F1->F2 on the left, SLOPE DOWN F2->F1 on the right).
    """
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._build_multi_floor_graph()

    def _add_edge(self, u, v):
        self.edges.setdefault(u, []).append(v)
        self.edges.setdefault(v, []).append(u)

    def _add_directed_edge(self, u, v):
        self.edges.setdefault(u, []).append(v)

    def _build_multi_floor_graph(self):
        # =====================================================================
        # FLOOR 1 (F1) - Ground Level (6 Spacious Slots Layout)
        # =====================================================================
        # Top Highway (Eastbound)
        self.nodes['ENTRANCE'] = (0, 50)
        self.nodes['SLOPE_UP_START'] = (65, 50)
        self.nodes['F1_TOP_1'] = (285, 50)
        self.nodes['F1_TOP_2'] = (675, 50)
        self.nodes['SLOPE_DOWN_END'] = (895, 50)
        self.nodes['EXIT'] = (960, 50)

        self._add_directed_edge('ENTRANCE', 'SLOPE_UP_START')
        self._add_directed_edge('SLOPE_UP_START', 'F1_TOP_1')
        self._add_directed_edge('F1_TOP_1', 'F1_TOP_2')
        self._add_directed_edge('F1_TOP_2', 'SLOPE_DOWN_END')
        self._add_directed_edge('SLOPE_DOWN_END', 'EXIT')

        # F1 Aisle 1 (Southbound): x = 285
        self.nodes['F1_A1_S03'] = (285, 188)
        self.nodes['F1_A1_S01'] = (285, 222)
        self.nodes['F1_A1_S04'] = (285, 432)
        self.nodes['F1_A1_S02'] = (285, 532)
        self.nodes['F1_BTM_1'] = (285, 600)

        self._add_edge('F1_TOP_1', 'F1_A1_S03')
        self._add_edge('F1_A1_S03', 'F1_A1_S01')
        self._add_edge('F1_A1_S01', 'F1_A1_S04')
        self._add_edge('F1_A1_S04', 'F1_A1_S02')
        self._add_edge('F1_A1_S02', 'F1_BTM_1')

        # F1 Bottom Connector Road (Aisle 1 to Aisle 2, Bidirectional)
        self._add_edge('F1_BTM_1', 'F1_BTM_2')

        # F1 Aisle 2 (Bidirectional for true shortest paths): x = 675
        self.nodes['F1_BTM_2'] = (675, 600)
        self.nodes['F1_A2_S05'] = (675, 532)
        self.nodes['F1_A2_S06'] = (675, 222)

        self._add_edge('F1_BTM_2', 'F1_A2_S05')
        self._add_edge('F1_A2_S05', 'F1_A2_S06')
        self._add_edge('F1_A2_S06', 'F1_TOP_2')

        # F1 Slots 1 to 6 Centers and Connections (100% Orthogonal Straight Lines)
        # Slot 1: Row 1 West (Car vertical at x=155, y=222)
        self.nodes['F1-S01'] = (155, 222)
        self._add_edge('F1-S01', 'F1_A1_S01')

        # Slot 2: Row 2 West (Car vertical at x=155, y=532)
        self.nodes['F1-S02'] = (155, 532)
        self._add_edge('F1-S02', 'F1_A1_S02')

        # Slot 3: Row 1 Center (Car horizontal at x=480, y=188) - Accessible from Aisle 1
        self.nodes['F1-S03'] = (480, 188)
        self._add_edge('F1-S03', 'F1_A1_S03')

        # Slot 4: Row 2 Center (Car horizontal at x=480, y=432) - Accessible from Aisle 1
        self.nodes['F1-S04'] = (480, 432)
        self._add_edge('F1-S04', 'F1_A1_S04')

        # Slot 5: Row 2 East (Car vertical at x=805, y=532)
        self.nodes['F1-S05'] = (805, 532)
        self._add_edge('F1-S05', 'F1_A2_S05')

        # Slot 6: Row 1 East (Car vertical at x=805, y=222)
        self.nodes['F1-S06'] = (805, 222)
        self._add_edge('F1-S06', 'F1_A2_S06')

        # Backward compatibility aliases for S1..S6 and 1..6
        for i in range(1, 7):
            f1_sid = f'F1-S0{i}'
            for alias in [f'S0{i}', f'S{i}', str(i)]:
                self.nodes[alias] = self.nodes[f1_sid]
                for nbr in self.edges.get(f1_sid, []):
                    self._add_edge(alias, nbr)

        # =====================================================================
        # INTER-FLOOR CONNECTING RAMPS / SLOPES
        # =====================================================================
        # SLOPE UP (F1 -> F2 on West)
        self.nodes['SLOPE_UP_MID'] = (65, 350)
        self.nodes['F2_ENTRY'] = (65, 650)
        self._add_edge('SLOPE_UP_START', 'SLOPE_UP_MID')
        self._add_edge('SLOPE_UP_MID', 'F2_ENTRY')

        # SLOPE DOWN (F2 -> F1 on East)
        self.nodes['F2_EXIT'] = (895, 650)
        self.nodes['SLOPE_DOWN_MID'] = (895, 350)
        self._add_edge('F2_EXIT', 'SLOPE_DOWN_MID')
        self._add_edge('SLOPE_DOWN_MID', 'SLOPE_DOWN_END')

        # =====================================================================
        # FLOOR 2 (F2) - Inverted Layout (Highway at Bottom, Storage at Top)
        # =====================================================================
        self.nodes['F2_BTM_1'] = (335, 650)
        self.nodes['F2_BTM_2'] = (625, 650)
        self._add_edge('F2_ENTRY', 'F2_BTM_1')
        self._add_edge('F2_BTM_1', 'F2_BTM_2')
        self._add_edge('F2_BTM_2', 'F2_EXIT')

        # F2 Aisles (Northbound from Bottom Highway to Top Crossroad)
        for i in range(1, 7):
            self.nodes[f'F2_A1_{i}'] = (335, 574 - (i-1)*70)
            self.nodes[f'F2_A2_{i}'] = (625, 574 - (i-1)*70)
        self.nodes['F2_TOP_1'] = (335, 155)
        self.nodes['F2_TOP_2'] = (625, 155)

        f2_a1 = ['F2_BTM_1'] + [f'F2_A1_{i}' for i in range(1, 7)] + ['F2_TOP_1']
        for i in range(len(f2_a1)-1):
            self._add_edge(f2_a1[i], f2_a1[i+1])

        f2_a2 = ['F2_BTM_2'] + [f'F2_A2_{i}' for i in range(1, 7)] + ['F2_TOP_2']
        for i in range(len(f2_a2)-1):
            self._add_edge(f2_a2[i], f2_a2[i+1])

        # F2 Top Crossroad (Leading to Top Bays S23-S28)
        f2_top = ['F2_TOP_1'] + [f'F2_TOP_S{i}' for i in range(23, 29)] + ['F2_TOP_2']
        for i, x in enumerate([323, 388, 453, 518, 583, 648], 23):
            self.nodes[f'F2_TOP_S{i}'] = (x, 155)
            self.nodes[f'F2-S{i}'] = (x, 75)
            self._add_edge(f'F2_TOP_S{i}', f'F2-S{i}')

        for i in range(len(f2_top)-1):
            self._add_edge(f2_top[i], f2_top[i+1])

        # F2 Bays to Aisles (Numbered bottom to top as per blueprint)
        for i in range(1, 7):
            self.nodes[f'F2-S{i:02d}'] = (237, 574 - (i-1)*70)
            self._add_edge(f'F2-S{i:02d}', f'F2_A1_{i}')

        for i in range(7, 12):
            self.nodes[f'F2-S{i:02d}'] = (432, 574 - (i-7)*70)
            self._add_edge(f'F2-S{i:02d}', f'F2_A1_{i-6}')

        for i in range(12, 17):
            self.nodes[f'F2-S{i:02d}'] = (528, 574 - (i-12)*70)
            self._add_edge(f'F2-S{i:02d}', f'F2_A2_{i-11}')

        for i in range(17, 23):
            self.nodes[f'F2-S{i:02d}'] = (722, 574 - (i-17)*70)
            self._add_edge(f'F2-S{i:02d}', f'F2_A2_{i-16}')

        # Backward compatibility aliases for S01-S06 and 1-6 -> F1-S01..F1-S06
        for i in range(1, 7):
            f1_sid = f'F1-S{i:02d}'
            if f1_sid in self.nodes:
                for alias in [f'S{i:02d}', f'S{i}', str(i)]:
                    self.nodes[alias] = self.nodes[f1_sid]
                    for nbr in self.edges.get(f1_sid, []):
                        self._add_edge(alias, nbr)

    def _euclidean_dist(self, node_a, node_b):
        x1, y1 = self.nodes[node_a]
        x2, y2 = self.nodes[node_b]
        return math.hypot(x2 - x1, y2 - y1)

    def resolve_slot_id(self, slot_id):
        """Resolves alias like S02 -> F1-S02 if not directly found."""
        if slot_id in self.nodes:
            return slot_id
        if slot_id.startswith('S') and f'F1-{slot_id}' in self.nodes:
            return f'F1-{slot_id}'
        return slot_id

    def find_shortest_path(self, start="ENTRANCE", target="S01", blocked_nodes=None):
        """
        A* algorithm to find optimal waypoint coordinates from start to target.
        Supports multi-floor traversal across ramps.
        """
        if blocked_nodes is None:
            blocked_nodes = set()

        start = self.resolve_slot_id(start)
        target = self.resolve_slot_id(target)

        if start not in self.nodes:
            start = "ENTRANCE"
        if target not in self.nodes:
            target = "F1-S01"

        open_set = []
        heapq.heappush(open_set, (0, start))
        
        came_from = {}
        g_score = {node: float('inf') for node in self.nodes}
        g_score[start] = 0
        
        f_score = {node: float('inf') for node in self.nodes}
        f_score[start] = self._euclidean_dist(start, target)

        visited = set()

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == target:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                
                coords_path = [{"node": n, "x": self.nodes[n][0], "y": self.nodes[n][1]} for n in path]
                
                # Determine target floor (1 or 2)
                target_floor = 2 if "F2" in target else 1
                
                return {
                    "path_nodes": path,
                    "coordinates": coords_path,
                    "distance_pixels": round(g_score[target], 2),
                    "target_floor": target_floor
                }

            visited.add(current)

            for neighbor in self.edges.get(current, []):
                if neighbor in blocked_nodes:
                    continue
                    
                tentative_g = g_score[current] + self._euclidean_dist(current, neighbor)
                
                if tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._euclidean_dist(neighbor, target)
                    if neighbor not in visited:
                        heapq.heappush(open_set, (f_score[neighbor], neighbor))

        # Fallback direct path
        return {
            "path_nodes": [start, target],
            "coordinates": [
                {"node": start, "x": self.nodes[start][0], "y": self.nodes[start][1]},
                {"node": target, "x": self.nodes[target][0], "y": self.nodes[target][1]}
            ],
            "distance_pixels": self._euclidean_dist(start, target),
            "target_floor": 2 if "F2" in target else 1
        }
