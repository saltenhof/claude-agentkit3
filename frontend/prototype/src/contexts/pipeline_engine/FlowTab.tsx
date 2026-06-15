// BC slice boundary: pipeline_engine owns FlowTab.
// The physical component lives in components/FlowTab.tsx (Concept-as-Code source).
// Productive imports must route through this slice boundary (AC2/MAJOR 8).
export { FlowTab } from '../../components/FlowTab';
