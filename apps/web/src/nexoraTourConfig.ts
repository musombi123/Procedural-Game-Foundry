export type TourStep = { id: string; target: string; title: string; body: string; action?: boolean };
export const NEXORA_TOUR: TourStep[] = [
  { id: "welcome", target: "[data-tour='welcome']", title: "Welcome to NEXORA", body: "Turn your video or character into a playable game. This quick tour shows you where to start." },
  { id: "pc", target: "[data-tour='pc-connect']", title: "Connect your PC", body: "Connect the NEXORA PC app to run heavy processing locally. Device access and readiness details appear when the desktop agent is available." },
  { id: "video", target: "[data-tour='video-upload']", title: "Add your video or portrait", body: "Choose your source media from the production workflow. Files are handled by your connected local engine; confirm the PC connection before large uploads.", action: true },
  { id: "assets", target: "[data-tour='assets']", title: "Character and assets", body: "Build or review the character and generated assets in the project collection. Assets are project-scoped and can be previewed here." },
  { id: "pipeline", target: "[data-tour='pipeline']", title: "Generation pipeline", body: "Follow the review-gated stages. Review each output and approve it before moving on." },
  { id: "preview", target: "[data-tour='preview']", title: "Preview and test", body: "Edit the world, inspect objects, and enter the live viewport to test your scene." },
  { id: "levels", target: "[data-tour='levels']", title: "Build your levels", body: "Use the world and scene editor to shape gameplay. Create additional levels through the game engine workflow when supported." },
  { id: "export", target: "[data-tour='export']", title: "Export and monetization", body: "Explore project monetization settings and export options. Export prices and platform availability are shown by the connected engine—not invented by this tour." },
  { id: "help", target: "[data-tour='help']", title: "Plans and help", body: "Check account and plan information in the connected product, or replay this tour any time. Ready? Start your first project." }
];
