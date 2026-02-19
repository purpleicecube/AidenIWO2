import { LayoutDashboard, ClipboardList, Plus, Activity, Settings, Layers, Brain, Bot, GitBranch, Wrench, FolderOpen, FlaskConical, MessageSquare } from "lucide-react";
import { useLocation, Link } from "wouter";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar";

const navigationItems = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Chat with Aiden", url: "/chat", icon: MessageSquare },
  { title: "Work Orders", url: "/work-orders", icon: ClipboardList },
  { title: "Submit Order", url: "/submit", icon: Plus },
  { title: "System Health", url: "/health", icon: Activity },
];

export function AppSidebar() {
  const [location] = useLocation();

  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <Link href="/">
          <div className="flex items-center gap-3 cursor-pointer" data-testid="link-logo">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary">
              <Layers className="w-5 h-5 text-primary-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold tracking-tight">AIDEN_PTIB</span>
              <span className="text-xs text-muted-foreground">Orchestration Engine</span>
            </div>
          </div>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navigationItems.map((item) => {
                const isActive = location === item.url || 
                  (item.url !== "/" && location.startsWith(item.url));
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      data-testid={`link-nav-${item.title.toLowerCase().replace(/\s/g, "-")}`}
                    >
                      <Link href={item.url}>
                        <item.icon className="w-4 h-4" />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Environments</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/workspace"} data-testid="link-nav-workspace">
                  <Link href="/workspace">
                    <FolderOpen className="w-4 h-4" />
                    <span>Workspace</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/sandbox"} data-testid="link-nav-sandbox">
                  <Link href="/sandbox">
                    <FlaskConical className="w-4 h-4" />
                    <span>Sandbox</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Architecture</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/architecture"} data-testid="link-nav-tier-overview">
                  <Link href="/architecture">
                    <Layers className="w-4 h-4" />
                    <span>Tier Overview</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Configuration</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/sub-agents"} data-testid="link-nav-sub-agents">
                  <Link href="/sub-agents">
                    <Bot className="w-4 h-4" />
                    <span>Sub-Agents</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/workflows"} data-testid="link-nav-workflows">
                  <Link href="/workflows">
                    <GitBranch className="w-4 h-4" />
                    <span>Workflows</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/tools"} data-testid="link-nav-tools">
                  <Link href="/tools">
                    <Wrench className="w-4 h-4" />
                    <span>Tools</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location === "/settings"} data-testid="link-nav-aiden-settings">
                  <Link href="/settings">
                    <Brain className="w-4 h-4" />
                    <span>Aiden Settings</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="p-4">
        <div className="text-xs text-muted-foreground">
          v1.0.0 MVP
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
