import { Navigate, Route, Routes } from "react-router";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { PlaygroundPage } from "@/pages/playground";

export function App() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <Routes>
          <Route path="/" element={<Navigate to="/playground" replace />} />
          <Route path="/playground" element={<PlaygroundPage />} />
        </Routes>
      </SidebarInset>
    </SidebarProvider>
  );
}
