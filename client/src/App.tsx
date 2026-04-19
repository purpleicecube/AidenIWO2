import { Switch, Route, useLocation } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { useAuth } from "@/hooks/use-auth";
import { Loader2 } from "lucide-react";
import NotFound from "@/pages/not-found";
import Dashboard from "@/pages/dashboard";
import WorkOrders from "@/pages/work-orders";
import WorkOrderDetail from "@/pages/work-order-detail";
import SubmitOrder from "@/pages/submit-order";
import SystemHealth from "@/pages/system-health";
import Architecture from "@/pages/architecture";
import Settings from "@/pages/settings";
import SubAgentsPage from "@/pages/sub-agents";
import WorkflowsPage from "@/pages/workflows";
import ToolsPage from "@/pages/tools";
import WorkspacePage from "@/pages/workspace";
import SandboxPage from "@/pages/sandbox";
import ChatPage from "@/pages/chat";
import LandingPage from "@/pages/landing";
import UserManagementPage from "@/pages/user-management";
import PipelinesPage from "@/pages/pipelines";
import AttributionsPage from "@/pages/attributions";
import StitchAccessPage from "@/pages/stitch-access";

function Router() {
  return (
    <Switch>
      <Route path="/" component={Dashboard} />
      <Route path="/work-orders" component={WorkOrders} />
      <Route path="/work-orders/:id" component={WorkOrderDetail} />
      <Route path="/submit" component={SubmitOrder} />
      <Route path="/health" component={SystemHealth} />
      <Route path="/architecture" component={Architecture} />
      <Route path="/settings" component={Settings} />
      <Route path="/sub-agents" component={SubAgentsPage} />
      <Route path="/workflows" component={WorkflowsPage} />
      <Route path="/tools" component={ToolsPage} />
      <Route path="/workspace" component={WorkspacePage} />
      <Route path="/sandbox" component={SandboxPage} />
      <Route path="/chat" component={ChatPage} />
      <Route path="/users" component={UserManagementPage} />
      <Route path="/pipelines" component={PipelinesPage} />
      <Route path="/attributions" component={AttributionsPage} />
      <Route path="/design-lab" component={StitchAccessPage} />
      <Route component={NotFound} />
    </Switch>
  );
}

function AuthenticatedApp() {
  const style = {
    "--sidebar-width": "16rem",
    "--sidebar-width-icon": "3rem",
  };

  return (
    <SidebarProvider style={style as React.CSSProperties}>
      <div className="flex h-screen w-full">
        <AppSidebar />
        <div className="flex flex-col flex-1 min-w-0">
          <header className="flex items-center justify-between gap-4 p-2 border-b sticky top-0 z-50 bg-background">
            <SidebarTrigger data-testid="button-sidebar-toggle" />
            <ThemeToggle />
          </header>
          <main className="flex-1 overflow-auto">
            <Router />
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}

function AppContent() {
  const { user, isLoading } = useAuth();
  const [location] = useLocation();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (location === "/attributions") {
    return <AttributionsPage />;
  }

  if (!user) {
    return <LandingPage />;
  }

  return <AuthenticatedApp />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <AppContent />
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
