require("dotenv").config();

const readline = require("readline");
const {
  AuthApiClient,
  TalkClient,
  KnownAuthStatusCode,
} = require("node-kakao");

const DEVICE_NAME = process.env.KAKAO_DEVICE_NAME || "JinroaBotPC";
const DEVICE_UUID = process.env.KAKAO_DEVICE_UUID || "jinroa-bot-device-001";

function ask(question) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

async function main() {
  console.log("진로아 NodeKakao 로그인 테스트 시작");

  const email = process.env.KAKAO_EMAIL;
  const password = process.env.KAKAO_PASSWORD;

  if (!email || !password) {
    console.log(".env에 KAKAO_EMAIL / KAKAO_PASSWORD가 없습니다.");
    return;
  }

  const form = {
    email,
    password,
    forced: true,
  };

  const api = await AuthApiClient.create(DEVICE_NAME, DEVICE_UUID);

  console.log("1차 로그인 시도...");
  let loginRes = await api.login(form);
  console.dir(loginRes, { depth: null });

  if (!loginRes.success) {
    if (loginRes.status === KnownAuthStatusCode.DEVICE_NOT_REGISTERED) {
      console.log("등록되지 않은 기기입니다. 카카오 인증번호 요청을 진행합니다.");

      const passcodeRes = await api.requestPasscode(form);
      console.log("인증번호 요청 결과:");
      console.dir(passcodeRes, { depth: null });

      if (!passcodeRes.success) {
        console.log("인증번호 요청 실패:", passcodeRes.status);
        return;
      }

      console.log("카카오톡 앱 또는 카카오 계정으로 인증번호가 전송되었을 수 있습니다.");
      const passcode = await ask("인증번호를 입력하세요: ");

      const registerRes = await api.registerDevice(form, passcode, true);
      console.log("기기 등록 결과:");
      console.dir(registerRes, { depth: null });

      if (!registerRes.success) {
        console.log("기기 등록 실패:", registerRes.status);
        return;
      }

      console.log("기기 등록 성공. 다시 로그인합니다.");

      loginRes = await api.login(form);
      console.log("2차 로그인 결과:");
      console.dir(loginRes, { depth: null });

      if (!loginRes.success) {
        console.log("2차 로그인 실패:", loginRes.status);
        return;
      }
    } else {
      console.log("로그인 실패:", loginRes.status);
      console.log("이 경우는 이메일/비밀번호 문제 또는 현재 node-kakao 로그인 호환 문제일 수 있습니다.");
      return;
    }
  }

  const client = new TalkClient();

  console.log("TalkClient 로그인 시도...");
  const talkLoginRes = await client.login(loginRes.result);
  console.dir(talkLoginRes, { depth: null });

  if (!talkLoginRes.success) {
    console.log("TalkClient 로그인 실패:", talkLoginRes.status);
    return;
  }

  console.log("카카오 로그인 성공!");
  console.log("이제 채팅방 수신 테스트 단계로 넘어갈 수 있습니다.");
}

main().catch((err) => {
  console.error("실행 중 오류:");
  console.error(err);
});