import { Navigate, Route, Routes } from "react-router";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AnalyticsPage } from "@/pages/analytics";
import { ObservabilityPage } from "@/pages/observability";
import { PlaygroundChatPage } from "@/pages/playground-chat";
import { PlaygroundResponsesPage } from "@/pages/playground-responses";

export function App() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <Routes>
          <Route path="/" element={<Navigate to="/playground/chat" replace />} />
          <Route path="/playground/chat" element={<PlaygroundChatPage />} />
          <Route path="/playground/responses" element={<PlaygroundResponsesPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/observability" element={<ObservabilityPage />} />
        </Routes>
      </SidebarInset>
    </SidebarProvider>
  );
}
