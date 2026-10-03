import { BarChart3Icon, MessageSquareIcon } from "lucide-react";
import { NavLink, useMatch } from "react-router";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

export function AppSidebar() {
  const isPlayground = useMatch("/playground") !== null;
  const isAnalytics = useMatch("/analytics") !== null;

  return (
    <Sidebar>
      <SidebarHeader>local-llm-server</SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isPlayground}
                  render={<NavLink to="/playground" />}
                >
                  <MessageSquareIcon />
                  <span>Playground</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isAnalytics}
                  render={<NavLink to="/analytics" />}
                >
                  <BarChart3Icon />
                  <span>Analytics</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
