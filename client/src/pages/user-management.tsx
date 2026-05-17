import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { usePageTitle } from "@/hooks/use-page-title";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Shield, Users, Loader2, Trash2, Send, Mail } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest } from "@/lib/queryClient";
import type { AuthUser } from "@shared/models/auth";

function roleBadgeVariant(role: string | undefined) {
  if (role === "admin") return "default" as const;
  if (role === "operator") return "secondary" as const;
  return "outline" as const;
}

export default function UserManagementPage() {
  usePageTitle("User Management");
  const { user: currentUser } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data: users, isLoading } = useQuery<AuthUser[]>({
    queryKey: ["/api/admin/users"],
  });

  const updateRoleMutation = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      await apiRequest("PUT", `/api/admin/users/${userId}/role`, { role });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/users"] });
      queryClient.invalidateQueries({ queryKey: ["/api/auth/user"] });
      toast({ title: "Role updated successfully" });
    },
    onError: (err: any) => {
      toast({ title: "Failed to update role", description: err.message, variant: "destructive" });
    },
  });

  const [inviteEmail, setInviteEmail] = useState("");

  const inviteMutation = useMutation({
    mutationFn: async (email: string) => {
      const res = await apiRequest("POST", "/api/admin/invite", { email });
      return res.json();
    },
    onSuccess: (data: any) => {
      toast({ title: "Invitation sent", description: data.message });
      setInviteEmail("");
    },
    onError: (err: any) => {
      toast({ title: "Failed to send invitation", description: err.message, variant: "destructive" });
    },
  });

  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      await apiRequest("DELETE", `/api/admin/users/${userId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/users"] });
      toast({ title: "User removed successfully" });
    },
    onError: (err: any) => {
      toast({ title: "Failed to remove user", description: err.message, variant: "destructive" });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold flex items-center gap-2" data-testid="text-page-title">
          <Users className="w-6 h-6" />
          User Management
        </h1>
        <p className="text-muted-foreground text-sm">
          Manage user accounts and role assignments. First user to sign in is automatically assigned Admin.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Mail className="w-5 h-5" />
            Invite User
          </CardTitle>
          <CardDescription>Send an email invitation to join the platform</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex gap-3"
            data-testid="form-invite-user"
            onSubmit={(e) => {
              e.preventDefault();
              if (inviteEmail.trim()) {
                inviteMutation.mutate(inviteEmail.trim());
              }
            }}
          >
            <Input
              type="email"
              placeholder="colleague@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="flex-1"
              data-testid="input-invite-email"
              required
            />
            <Button
              type="submit"
              disabled={inviteMutation.isPending || !inviteEmail.trim()}
              data-testid="button-send-invite"
            >
              {inviteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin mr-2" />
              ) : (
                <Send className="w-4 h-4 mr-2" />
              )}
              Send Invite
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Users ({users?.length || 0})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 p-0">
          {!users?.length ? (
            <p className="text-center text-muted-foreground py-8">No users found</p>
          ) : (
            <div className="divide-y">
              {users.map((u) => {
                const initials = `${(u.firstName || "")[0] || ""}${(u.lastName || "")[0] || ""}`.toUpperCase() || "U";
                const isSelf = u.id === currentUser?.id;
                return (
                  <div key={u.id} className="flex items-center gap-4 px-6 py-4" data-testid={`row-user-${u.id}`}>
                    <Avatar className="w-10 h-10">
                      <AvatarImage src={u.profileImageUrl || undefined} />
                      <AvatarFallback>{initials}</AvatarFallback>
                    </Avatar>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {[u.firstName, u.lastName].filter(Boolean).join(" ") || "Unnamed"}
                        {isSelf && <span className="text-muted-foreground ml-1">(you)</span>}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">{u.email || "No email"}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      {isSelf ? (
                        <Badge variant={roleBadgeVariant(u.role)} className="text-xs" data-testid={`badge-role-${u.id}`}>
                          <Shield className="w-3 h-3 mr-1" />
                          {u.role}
                        </Badge>
                      ) : (
                        <>
                          <Select
                            value={u.role}
                            onValueChange={(role) => updateRoleMutation.mutate({ userId: u.id, role })}
                            data-testid={`select-role-${u.id}`}
                          >
                            <SelectTrigger className="w-28 h-8 text-xs" data-testid={`select-role-trigger-${u.id}`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="admin">Admin</SelectItem>
                              <SelectItem value="operator">Operator</SelectItem>
                              <SelectItem value="viewer">Viewer</SelectItem>
                            </SelectContent>
                          </Select>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                            data-testid={`button-delete-user-${u.id}`}
                            disabled={deleteUserMutation.isPending}
                            onClick={() => {
                              if (confirm(`Remove ${[u.firstName, u.lastName].filter(Boolean).join(" ") || "this user"}? They will need to sign in again to regain access.`)) {
                                deleteUserMutation.mutate(u.id);
                              }
                            }}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
