import { defineConfig } from "@neondatabase/config/v1";

/**
 * NEXORA's persistent data plane.
 *
 * Postgres is provisioned by every Neon project. Creator uploads and build
 * artifacts live in a private, branch-scoped bucket. Identity remains the
 * existing RevelaCode identity provider; this project deliberately does not
 * create a second Neon Auth tenant.
 */
export default defineConfig({
  buckets: {
    "nexora-assets": {},
  },
});
