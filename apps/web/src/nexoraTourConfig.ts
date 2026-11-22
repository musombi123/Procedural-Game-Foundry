export type TourStep = {
  id: string;
  title: string;
  body: string;
  target?: string;
  action?: string;
};

export const NEXORA_TOUR_VERSION = 1;

export const NEXORA_TOUR: TourStep[] = [
  { id: "welcome", title: "Welcome to NEXORA", body: "Turn your idea into a playable game. This short tour shows the current workspace and the path from source media to a build.", target: '[data-tour="workspace-home"]' },
  { id: "connect", title: "Connect your PC", body: "NEXORA's Local Agent runs heavy processing on your computer. Connect the Local Agent before starting device-side work. Device access and hardware readiness are shown by the agent; no permission is granted silently.", target: '[data-tour="connect-pc"]' },
  { id: "video", title: "Add your video", body: "Create a project and add a video in the Movie → playable game panel. The current pipeline uploads the selected file to the configured local Foundry API; confirm the Local Agent connection before uploading.", target: '[data-tour="upload-video"]' },
  { id: "assets", title: "Character and assets", body: "The production panels build your player, environment, actors and props. Generated and uploaded files are collected in Asset Collection Center.", target: '[data-tour="asset-center"]' },
  { id: "pipeline", title: "Follow the pipeline", body: "Work through analysis, player, environment, actors and props, audio, gameplay, and assembly. Review-gated stages keep approvals visible.", target: '[data-tour="pipeline"]' },
  { id: "preview", title: "Preview and test", body: "Open World Foundry or Scene Editor to inspect the 3D world, place objects, adjust terrain and enter the playable preview.", target: '[data-tour="preview"]' },
  { id: "levels", title: "Build more levels", body: "Use the project's level tools to expand the game. If the current project has no level manager, continue in World Foundry and use the level/export controls available in the paired desktop workflow.", target: '[data-tour="levels"]' },
  { id: "export", title: "Export and monetization", body: "Use the export tools exposed by your paired NEXORA desktop engine to package the project. Monetization Center currently stores configuration only; platform SDKs and live billing still require separate integration.", target: '[data-tour="monetization"]' },
  { id: "help", title: "Plans, support and help", body: "Your account plan and support options belong to the signed-in NEXORA account. Choose Help → Take the tour any time to replay this walkthrough. You're ready to start building.", target: '[data-tour="help"]' }
];
