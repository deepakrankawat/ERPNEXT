from __future__ import annotations

import json
import frappe
from frappe import _


NODE_TYPES = {
	"Trigger",
	"Action",
	"AI",
	"Human",
	"Control",
	"SOP",
	"Events",
	"Commercial",
}


@frappe.whitelist()
def validate_workflow_graph(graph_json: str | dict):
	"""Validate workflow graph structure for cycles, unreachable nodes, and errors (WFL-002)."""
	if isinstance(graph_json, str):
		try:
			graph = json.loads(graph_json)
		except Exception as e:
			return {"is_valid": False, "errors": [f"Invalid JSON payload: {str(e)}"]}
	else:
		graph = graph_json

	nodes = graph.get("nodes", [])
	edges = graph.get("edges", [])

	errors = []
	warnings = []

	if not nodes:
		return {"is_valid": False, "errors": ["Workflow graph contains no nodes."]}

	node_ids = {node["id"] for node in nodes if "id" in node}
	if len(node_ids) != len(nodes):
		errors.append("Duplicate or missing node IDs detected.")

	# Check node types
	start_nodes = []
	for node in nodes:
		n_type = node.get("type")
		if n_type not in NODE_TYPES:
			errors.append(f"Node '{node.get('id')}' has invalid node type '{n_type}'.")
		if n_type == "Trigger" or node.get("is_start"):
			start_nodes.append(node["id"])

	if not start_nodes:
		warnings.append("No Trigger or Start node defined in graph.")

	# Build adjacency list
	adjacency = {node_id: [] for node_id in node_ids}
	in_degree = {node_id: 0 for node_id in node_ids}

	for edge in edges:
		src = edge.get("source")
		tgt = edge.get("target")
		if src not in node_ids:
			errors.append(f"Edge references non-existent source node '{src}'.")
		if tgt not in node_ids:
			errors.append(f"Edge references non-existent target node '{tgt}'.")
		if src in node_ids and tgt in node_ids:
			adjacency[src].append(tgt)
			in_degree[tgt] += 1

	# Cycle detection using Kahn's algorithm (Topological sort)
	queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
	visited_count = 0
	while queue:
		curr = queue.pop(0)
		visited_count += 1
		for neighbor in adjacency[curr]:
			in_degree[neighbor] -= 1
			if in_degree[neighbor] == 0:
				queue.append(neighbor)

	if visited_count < len(node_ids):
		errors.append("Cycle detected without loop limit in workflow graph.")

	# Check reachability from every explicit trigger/start node.
	reachable = set()
	stack = list(start_nodes)
	while stack:
		current = stack.pop()
		if current in reachable:
			continue
		reachable.add(current)
		stack.extend(adjacency.get(current, []))
	unreachable = set(node_ids) - reachable if start_nodes else set()
	if unreachable:
		warnings.append(f"Unreachable nodes detected: {list(unreachable)}")

	return {
		"is_valid": len(errors) == 0,
		"errors": errors,
		"warnings": warnings,
		"node_count": len(nodes),
		"edge_count": len(edges),
	}
