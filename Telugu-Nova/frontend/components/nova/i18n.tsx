'use client';

import { createContext, useContext } from 'react';

/**
 * Interface language. English by default; the student can switch in the chat
 * panel, and the same choice tells the teachers which language to speak (the
 * token route reads the `nova_lang` cookie, the live switch goes over the
 * board text stream).
 */

export const LANGS = [
  { code: 'en', label: 'English' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'hi', label: 'हिंदी' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'kn', label: 'ಕನ್ನಡ' },
] as const;
export type Lang = (typeof LANGS)[number]['code'];

const en = {
  tagline: 'Your live AI teacher',
  readyBody:
    'Ask about anything — code, finance, health, science. Acharya explains it on a live board.',
  start: 'Start class',
  micNote: 'We will ask for microphone access',
  connecting: 'Connecting…',
  connectingBody: 'One moment — Acharya is joining.',
  listening: 'Listening',
  thinking: 'Thinking…',
  speaking: 'Acharya is speaking',
  you: 'You',
  nova: 'Acharya',
  transcriptEmpty: 'Speak — your conversation appears here',
  micOff: 'Mute mic',
  micOn: 'Unmute mic',
  endCall: 'End class',
  ended: 'Class ended',
  endedTurns: (n: number) => `We talked ${n} times. Come back anytime!`,
  endedNone: 'Come back anytime.',
  again: 'Start again',
  language: 'Language',
  boardEmptyTitle: 'What shall we learn?',
  boardEmptyBody:
    'Ask Acharya anything — it draws and explains here. Circle anything you do not understand and it stops to explain that part.',
  dontGet: "I don't get this",
  looking: 'Acharya is looking…',
  preparing: 'Preparing the board…',
  researchTitle: 'research · latest',
  researchSub: 'Live from the web, with sources',
  researching: 'researching…',
  generating: 'generating…',
  micDeniedTitle: 'Microphone is blocked',
  micDeniedBody: 'The browser is not allowing the microphone. Acharya needs it to hear you.',
  micFix: ['Click the lock icon in the address bar', 'Set Microphone to Allow', 'Reload this page'],
  retry: 'Try again',
  earlier: 'Earlier classes',
  thisClass: 'This class',
  history: 'Previous chats',
  newChat: 'New chat',
  back: 'Back',
  home: 'Home',
  clearHistory: 'Clear',
};
export type Strings = typeof en;

const te: Strings = {
  ...en,
  tagline: 'నీ live AI టీచర్',
  readyBody:
    'ఏదైనా అడుగు — code, finance, health, science. ఆచార్య live board మీద explain చేస్తుంది.',
  start: 'క్లాస్ మొదలుపెడదాం',
  micNote: 'మైక్ అనుమతి అడుగుతుంది',
  connecting: 'కలుపుతున్నా…',
  connectingBody: 'ఒక్క సెకను — ఆచార్య వస్తుంది.',
  listening: 'వింటున్నా',
  thinking: 'ఆలోచిస్తున్నా…',
  speaking: 'ఆచార్య మాట్లాడుతుంది',
  you: 'నువ్వు',
  nova: 'ఆచార్య',
  transcriptEmpty: 'మాట్లాడు — ఇక్కడ కనిపిస్తుంది',
  micOff: 'మైక్ ఆఫ్',
  micOn: 'మైక్ ఆన్',
  endCall: 'క్లాస్ ఆపు',
  ended: 'క్లాస్ అయిపోయింది',
  endedTurns: (n) => `${n} సార్లు మాట్లాడుకున్నాం. మళ్ళీ రా!`,
  endedNone: 'మళ్ళీ ఎప్పుడైనా రా.',
  again: 'మళ్ళీ మొదలుపెడదాం',
  language: 'భాష',
  boardEmptyTitle: 'ఏం నేర్చుకుందాం?',
  boardEmptyBody:
    'ఆచార్య ని ఏదైనా అడుగు — ఇక్కడ గీసి explain చేస్తుంది. అర్థం కాని దాని చుట్టూ circle గీయి.',
  dontGet: 'ఇది అర్థం కాలేదు',
  looking: 'ఆచార్య చూస్తుంది…',
  preparing: 'బోర్డ్ సిద్ధం చేస్తున్నా…',
  researching: 'వెతుకుతున్నా…',
  generating: 'తయారు చేస్తున్నా…',
  retry: 'మళ్ళీ try చెయ్యి',
  newChat: 'కొత్త chat',
  back: 'వెనక్కి',
  home: 'హోమ్',
  history: 'పాత chats',
};

const hi: Strings = {
  ...en,
  tagline: 'आपका live AI टीचर',
  readyBody: 'कुछ भी पूछिए — code, finance, health, science. Acharya live board पर समझाएगा.',
  start: 'क्लास शुरू करें',
  micNote: 'माइक की अनुमति मांगी जाएगी',
  connecting: 'जुड़ रहे हैं…',
  connectingBody: 'एक पल — Acharya आ रहा है.',
  listening: 'सुन रहा हूँ',
  thinking: 'सोच रहा हूँ…',
  speaking: 'Acharya बोल रहा है',
  you: 'आप',
  transcriptEmpty: 'बोलिए — बातचीत यहाँ दिखेगी',
  micOff: 'माइक बंद',
  micOn: 'माइक चालू',
  endCall: 'क्लास खत्म',
  ended: 'क्लास खत्म हुई',
  endedTurns: (n) => `हमने ${n} बार बात की. फिर आइए!`,
  endedNone: 'फिर कभी आइए.',
  again: 'फिर शुरू करें',
  language: 'भाषा',
  boardEmptyTitle: 'क्या सीखें?',
  boardEmptyBody: 'Acharya से कुछ भी पूछिए — यहाँ बनाकर समझाएगा. जो समझ न आए उस पर circle बनाइए.',
  dontGet: 'यह समझ नहीं आया',
  looking: 'Acharya देख रहा है…',
  preparing: 'बोर्ड तैयार हो रहा है…',
  researching: 'खोज रहा है…',
  generating: 'बना रहा है…',
  retry: 'फिर कोशिश करें',
  newChat: 'नई चैट',
  back: 'वापस',
  home: 'होम',
  history: 'पिछली चैट',
};

const ta: Strings = {
  ...en,
  tagline: 'உங்கள் live AI ஆசிரியர்',
  start: 'வகுப்பைத் தொடங்கு',
  connecting: 'இணைக்கிறது…',
  listening: 'கேட்கிறேன்',
  thinking: 'யோசிக்கிறேன்…',
  speaking: 'Acharya பேசுகிறது',
  you: 'நீங்கள்',
  micOff: 'மைக் அணை',
  micOn: 'மைக் இயக்கு',
  endCall: 'வகுப்பை முடி',
  ended: 'வகுப்பு முடிந்தது',
  again: 'மீண்டும் தொடங்கு',
  language: 'மொழி',
  boardEmptyTitle: 'என்ன கற்றுக்கொள்வோம்?',
  dontGet: 'இது புரியவில்லை',
  looking: 'Acharya பார்க்கிறது…',
};

const kn: Strings = {
  ...en,
  tagline: 'ನಿಮ್ಮ live AI ಶಿಕ್ಷಕ',
  start: 'ತರಗತಿ ಶುರು ಮಾಡಿ',
  connecting: 'ಸಂಪರ್ಕಿಸುತ್ತಿದೆ…',
  listening: 'ಕೇಳುತ್ತಿದ್ದೇನೆ',
  thinking: 'ಯೋಚಿಸುತ್ತಿದ್ದೇನೆ…',
  speaking: 'Acharya ಮಾತನಾಡುತ್ತಿದೆ',
  you: 'ನೀವು',
  micOff: 'ಮೈಕ್ ಆಫ್',
  micOn: 'ಮೈಕ್ ಆನ್',
  endCall: 'ತರಗತಿ ಮುಗಿಸಿ',
  ended: 'ತರಗತಿ ಮುಗಿಯಿತು',
  again: 'ಮತ್ತೆ ಶುರು ಮಾಡಿ',
  language: 'ಭಾಷೆ',
  boardEmptyTitle: 'ಏನು ಕಲಿಯೋಣ?',
  dontGet: 'ಇದು ಅರ್ಥವಾಗಲಿಲ್ಲ',
  looking: 'Acharya ನೋಡುತ್ತಿದೆ…',
};

export const STRINGS: Record<Lang, Strings> = { en, te, hi, ta, kn };

export const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: 'en',
  setLang: () => {},
});

export function useT(): Strings {
  return STRINGS[useContext(LangContext).lang] ?? en;
}

export function readLangCookie(): Lang {
  if (typeof document === 'undefined') return 'en';
  const m = document.cookie.match(/(?:^|; )nova_lang=([a-z]{2})/);
  const code = m?.[1] as Lang | undefined;
  return code && code in STRINGS ? code : 'en';
}

export function writeLangCookie(lang: Lang) {
  document.cookie = `nova_lang=${lang}; path=/; max-age=31536000; samesite=lax`;
}
