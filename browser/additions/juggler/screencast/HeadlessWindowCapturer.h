/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#pragma once

#include <memory>
#include <set>
#ifdef XP_WIN
typedef int pid_t;  // libwebrtc headers reference pid_t which is POSIX-only
#endif
#include "api/video/video_frame.h"
#include "api/video/video_sink_interface.h"
#include "modules/video_capture/video_capture.h"
#include "rtc_base/deprecated/recursive_critical_section.h"
#include "video_engine/desktop_capture_impl.h"

// Compatibility namespace alias: libwebrtc converted rtc:: to webrtc:: in Fx150
namespace rtc = webrtc;

class nsIWidget;

namespace mozilla {

namespace widget {
class HeadlessWidget;
}

class HeadlessWindowCapturer : public webrtc::VideoCaptureModuleEx {
 public:
  static rtc::scoped_refptr<webrtc::VideoCaptureModuleEx> Create(mozilla::widget::HeadlessWidget*);

  void RegisterCaptureDataCallback(
      rtc::VideoSinkInterface<webrtc::VideoFrame>* dataCallback) override;
  void DeRegisterCaptureDataCallback() override;
  void DeRegisterCaptureDataCallback(
      rtc::VideoSinkInterface<webrtc::VideoFrame>* dataCallback) override;
  int32_t StopCaptureIfAllClientsClose() override;

  void RegisterRawFrameCallback(webrtc::RawFrameCallback* rawFrameCallback) override;
  void RegisterCaptureDataCallback(webrtc::RawVideoSinkInterface* dataCallback) override;
  void DeRegisterRawFrameCallback(webrtc::RawFrameCallback* rawFrameCallback) override;

  int32_t SetCaptureRotation(webrtc::VideoRotation) override { return -1; }
  bool SetApplyRotation(bool) override { return false; }
  bool GetApplyRotation() override { return true; }

  const char* CurrentDeviceName() const override { return "Headless window"; }

  // Platform dependent
  int32_t StartCapture(const webrtc::VideoCaptureCapability& capability) override;
  bool FocusOnSelectedSource() override { return false; }
  int32_t StopCapture() override;
  bool CaptureStarted() override;
  int32_t CaptureSettings(webrtc::VideoCaptureCapability& settings) override {
    return -1;
  }

 protected:
  HeadlessWindowCapturer(mozilla::widget::HeadlessWidget*);
  ~HeadlessWindowCapturer() override;

 private:
  void NotifyFrameCaptured(const webrtc::VideoFrame& frame);

  RefPtr<mozilla::widget::HeadlessWidget> mWindow;
  rtc::RecursiveCriticalSection _callBackCs;
  std::set<rtc::VideoSinkInterface<webrtc::VideoFrame>*> _dataCallBacks;
  std::set<webrtc::RawFrameCallback*> _rawFrameCallbacks;
};

}  // namespace mozilla
