export interface User {
  id: string;
  email: string;
  display_name: string;
  tenant_id: string | null;
  products: any[];
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}
