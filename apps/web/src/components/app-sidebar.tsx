import { ActivityIcon, BarChart3Icon, MessageSquareIcon } from "lucide-react";
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
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";

export function AppSidebar() {
  const isChat = useMatch("/playground/chat") !== null;
  const isResponses = useMatch("/playground/responses") !== null;
  const isAnalytics = useMatch("/analytics") !== null;
  const isObservability = useMatch("/observability") !== null;

  return (
    <Sidebar>
      <SidebarHeader>local-llm-server</SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton render={<div />}>
                  <MessageSquareIcon />
                  <span>Playground</span>
                </SidebarMenuButton>
                <SidebarMenuSub>
                  <SidebarMenuSubItem>
                    <SidebarMenuSubButton
                      isActive={isChat}
                      render={<NavLink to="/playground/chat" />}
                    >
                      <span>Chat</span>
                    </SidebarMenuSubButton>
                  </SidebarMenuSubItem>
                  <SidebarMenuSubItem>
                    <SidebarMenuSubButton
                      isActive={isResponses}
                      render={<NavLink to="/playground/responses" />}
                    >
                      <span>Responses</span>
                    </SidebarMenuSubButton>
                  </SidebarMenuSubItem>
                </SidebarMenuSub>
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
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isObservability}
                  render={<NavLink to="/observability" />}
                >
                  <ActivityIcon />
                  <span>Observability</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
