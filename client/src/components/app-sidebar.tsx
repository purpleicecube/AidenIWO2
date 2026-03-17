import { LayoutDashboard, ClipboardList, Plus, Activity, Layers, Brain, Bot, GitBranch, Wrench, FolderOpen, FlaskConical, MessageSquare, Users, LogOut, Shield } from "lucide-react";
import { useLocation, Link } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  { title: "Dashboard", url: "/", icon: LayoutDashboard, minRole: "viewer" },
  { title: "Chat with Aiden", url: "/chat", icon: MessageSquare, minRole: "viewer" },
  { title: "Work Orders", url: "/work-orders", icon: ClipboardList, minRole: "viewer" },
  { title: "Submit Order", url: "/submit", icon: Plus, minRole: "operator" },
  { title: "System Health", url: "/health", icon: Activity, minRole: "viewer" },
];

const environmentItems = [
  { title: "Workspace", url: "/workspace", icon: FolderOpen, minRole: "operator" },
  { title: "Sandbox", url: "/sandbox", icon: FlaskConical, minRole: "operator" },
];

const configItems = [
  { title: "Sub-Agents", url: "/sub-agents", icon: Bot, minRole: "admin" },
  { title: "Workflows", url: "/workflows", icon: GitBranch, minRole: "admin" },
  { title: "Tools", url: "/tools", icon: Wrench, minRole: "admin" },
  { title: "Aiden Settings", url: "/settings", icon: Brain, minRole: "admin" },
  { title: "User Management", url: "/users", icon: Users, minRole: "admin" },
];

const ROLE_LEVEL: Record<string, number> = { admin: 3, operator: 2, viewer: 1 };

function roleBadgeVariant(role: string) {
  if (role === "admin") return "default";
  if (role === "operator") return "secondary";
  return "outline";
}

export function AppSidebar() {
  const [location] = useLocation();
  const { user } = useAuth();
  const userRole = (user as any)?.role || "viewer";
  const userLevel = ROLE_LEVEL[userRole] || 1;
  const { data: healthData } = useQuery<{ version: string }>({
    queryKey: ["/api/health"],
    staleTime: 300_000, // 5 min
  });

  const canSee = (minRole: string) => userLevel >= (ROLE_LEVEL[minRole] || 1);

  const renderItems = (items: typeof navigationItems) =>
    items.filter(item => canSee(item.minRole)).map((item) => {
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
    });

  const initials = user
    ? `${(user.firstName || "")[0] || ""}${(user.lastName || "")[0] || ""}`.toUpperCase() || "U"
    : "U";

  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <Link href="/">
          <div className="flex items-center gap-3 cursor-pointer" data-testid="link-logo">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary">
              <Layers className="w-5 h-5 text-primary-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold tracking-tight">AIDEN_IWO2</span>
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
              {renderItems(navigationItems)}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {environmentItems.some(i => canSee(i.minRole)) && (
          <SidebarGroup>
            <SidebarGroupLabel>Environments</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {renderItems(environmentItems)}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}

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

        {configItems.some(i => canSee(i.minRole)) && (
          <SidebarGroup>
            <SidebarGroupLabel>Configuration</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {renderItems(configItems)}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter className="p-4 space-y-3">
        {user && (
          <div className="flex items-center gap-3">
            <Avatar className="w-8 h-8">
              <AvatarImage src={user.profileImageUrl || undefined} />
              <AvatarFallback className="text-xs">{initials}</AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate" data-testid="text-user-name">
                {user.firstName || user.email || "User"}
              </p>
              <Badge variant={roleBadgeVariant(userRole)} className="text-[10px] h-4 px-1.5" data-testid="text-user-role">
                <Shield className="w-2.5 h-2.5 mr-0.5" />
                {userRole}
              </Badge>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" data-testid="button-logout" onClick={() => { window.location.href = "/api/logout"; }}>
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          AIDEN_IWO2 v{healthData?.version || "..."}
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
