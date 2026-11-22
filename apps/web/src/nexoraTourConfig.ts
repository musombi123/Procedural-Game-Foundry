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
  { id: "connect", title: "Connect your PC", body: "NEXORA's Local Agent runs heavy processing on your computer. Connect the Local Agent before starting device-side work. Device access and hardware readiness are shown by the agent; no permission is granted silently.", target: '[data-tour="connect-pc"] .button.primary' },
  { id: "video", title: "Add your video", body: "If you have not created a project, use the highlighted action first. Then choose a video in Movie → playable game. The selected file is sent to your connected local Foundry engine for processing.", target: '[data-tour="upload-video"]' },
  { id: "assets", title: "Character and assets", body: "The production panels build your player, environment, actors and props. Generated and uploaded files are collected in Asset Collection Center.", target: '[data-tour="asset-center"]' },
  { id: "pipeline", title: "Follow the pipeline", body: "Work through analysis, player, environment, actors and props, audio, gameplay, and assembly. Review-gated stages keep approvals visible.", target: '[data-tour="pipeline"]' },
  { id: "preview", title: "Preview and test", body: "Open World Foundry or Scene Editor to inspect the 3D world, place objects, adjust terrain and enter the playable preview.", target: '[data-tour="world-nav"]' },
  { id: "levels", title: "Build more levels", body: "The current frontend does not yet include a multi-level manager. World Foundry edits the current scene; Level 2 and later need a dedicated level workflow.", target: '[data-tour="levels"]' },
  { id: "export", title: "Export and monetization", body: "The Export Center and Android/PC export selector are not yet exposed in this frontend. NEXORA's stated starting price is KES 499, but live quotes and checkout are not connected. Monetization Center stores configuration only; platform SDKs and billing are not active.", target: '[data-tour="monetization"]' },
  { id: "help", title: "Plans, support and help", body: "Help & Shortcuts contains keyboard guidance and the tour replay action. Plan, payment and support links are not yet surfaced in this workspace. You can now start building.", target: '[data-tour="help-nav"]' }
];
