import { AirbyteRequestService } from "core/request/AirbyteRequestService";

import { User } from "./types";

export class UserService extends AirbyteRequestService {
  get url(): string {
    return "v1/users";
  }

  public async getByEmail(email: string): Promise<User> {
    return this.fetch<User>(`${this.url}/get_by_email`, {
      email,
    });
  }

  public async getByAuthId(authUserId: string, authProvider: string): Promise<User> {
    return this.fetch<User>(`${this.url}/get_by_auth_id`, {
      authUserId,
      authProvider,
    });
  }

  public async changeEmail(email: string): Promise<void> {
    return this.fetch<void>(`${this.url}/update`, {
      email,
    });
  }

  public async create(user: {
    authUserId: string;
    authProvider: string;
    email: string;
    name: string;
    companyName: string;
    news: boolean;
    invitedWorkspaceId?: string;
    status?: "invited";
  }): Promise<User> {
    return this.fetch<User>(`v1/web_backend/users/create`, user);
  }

  public async remove(workspaceId: string, email: string): Promise<void> {
    return this.fetch(`v1/web_backend/cloud_workspaces/revoke_user`, {
      email,
      workspaceId,
    });
  }

  public async invite(
    users: {
      email: string;
    }[],
    workspaceId: string
  ): Promise<User[]> {
    return Promise.all(
      users.map(async (user) =>
        this.fetch<User>(`v1/web_backend/cloud_workspaces/invite_with_signin_link`, {
          email: user.email,
          workspaceId,
        })
      )
    );
  }

  public async listByWorkspaceId(workspaceId: string): Promise<User[]> {
    const { users } = await this.fetch<{ users: User[] }>(`v1/web_backend/permissions/list_users_by_workspace`, {
      workspaceId,
    });

    return users;
  }
}
