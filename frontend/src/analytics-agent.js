const slug = "keme-business-analytics";
const legacySlug = "business-analytics";

export const isAnalyticsAgent = (value) => value === slug || value === legacySlug;

export function findAgent(agents, requestedSlug) {
  return agents.find((agent) => agent.slug === requestedSlug)
    || (requestedSlug === legacySlug ? agents.find((agent) => agent.slug === slug) : undefined);
}
