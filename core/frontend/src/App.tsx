import { Routes, Route } from "react-router-dom";
import Home from "./pages/home";
import McpManagerPage from "./pages/mcp-manager";
import MyAgents from "./pages/my-agents";
import Workspace from "./pages/workspace";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/mcp-manager" element={<McpManagerPage />} />
      <Route path="/my-agents" element={<MyAgents />} />
      <Route path="/workspace" element={<Workspace />} />
    </Routes>
  );
}

export default App;
