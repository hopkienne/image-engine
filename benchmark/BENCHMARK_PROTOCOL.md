# Quy trình benchmark RAW nhiều engine v1.0

**Ngày:** 30/09/2026 · **Trạng thái:** Proposed · **Mục tiêu:** bằng chứng kỹ thuật và
so sánh ảnh nền cho R-02/G2. Không phải chứng nhận thẩm mỹ, dynamic range hoặc mobile.

## 1. Ba câu hỏi và ba loại bằng chứng

| Câu hỏi | Bằng chứng phù hợp | Không được suy diễn |
|---|---|---|
| Engine thực hiện đúng contract? | Oracle/unit/integration, source hash, geometry, config effect, export | Nhiều test pass không chứng minh màu đẹp |
| Ảnh nền có khác biệt đáng điều tra? | Cùng RAW, converter độc lập ở mức ứng dụng, thông số công khai, ROI/diff | Không coi một converter là đáp án đúng |
| Ảnh đủ dùng cho app? | Chất lượng trên scope đã chốt, review holdout, dữ liệu kiểm soát khi cần | Không tự nghiệm thu chỉ từ histogram hoặc AI review |

Hai converter có thể chia sẻ decoder/profile hoặc dòng thuật toán. Ghi dependency
thực tế trong engine lock; không gọi so sánh 3 engine là 3 phép đo độc lập hoàn toàn.
RawTherapee đã đưa LibRaw vào một số phiên bản; đây là lý do phải kiểm tra bản cài,
không suy luận mức độc lập từ tên chương trình. [S08]

Benchmark không yêu cầu engine dự án tái tạo default của đối thủ. Một khác biệt
có thể do tone curve, crop, profile, WB, gamut mapping hoặc sharpen, không phải bug.

## 2. Phạm vi, nhánh chạy và stop rule

### 2.1. Kích thước mẫu

| Mốc | Số RAW mục tiêu | Điều kiện |
|---|---:|---|
| Smoke | 1–3 trong pilot | Mỗi adapter tạo được output thật và log |
| Pilot | 12 | Đa dạng vừa đủ để phát hiện cấu hình/normalization sai |
| Standard | 40 tổng, có thể gồm pilot | Pipeline/metric ổn, profile/policy đã khóa, còn quota |
| Extended | 100 tổng | Chỉ khi chủ dự án bật; không mặc định |

Pilot thuộc development. Standard dự kiến 28 development + 12 holdout; tách theo
scene/session, không chỉ file. Nếu không đủ scene độc lập, ghi số thực và lý do.
Nhiều RAW cùng cảnh hoặc camera không đại diện mẫu ngẫu nhiên thị trường.

Ngân sách mặc định: tổng tải RAW 6 GiB; một file tối đa 256 MiB/120 MP;
workspace corpus+output 30 GiB; giữ 10 GiB trống; mỗi lần 1 download và 1 render.
Đo byte thực; dự trù dung lượng output từ dimensions/dtype trước batch. Dừng mở rộng
khi thiếu tài nguyên, giữ report PARTIAL. Không tự giảm độ phân giải ảnh đo để đủ quota.

### 2.2. Hai nhánh xử lý

**BASE_CONTROLLED** là nhánh chính: loại bỏ chỉnh sáng tạo và xử lý chi tiết tùy chọn
để nghiên cứu nền. **DEFAULT_RENDER** là nhánh phụ giúp hiểu trải nghiệm mặc định của
mỗi sản phẩm. Không xếp hai nhánh chung một bảng số liệu rồi gọi là so công bằng.

BASE không được đạt bằng cách tắt cả camera profile/WB/chuyển màu. Nếu giữ tone mapper
là cần thiết để dựng SDR, ghi tên/version/params; nếu vô hiệu hóa được thì ghi đó là
nhánh diagnostic khác. Không tồn tại một cờ "neutral" bảo đảm các developer có cùng
base rendering.

### 2.3. Phạm vi camera

Camera được app công bố hỗ trợ: required. Camera ngoài scope: exploratory. File required
không đọc được vẫn là kết quả không đạt khả năng xử lý trên fixture đó. File exploratory
không đọc được là coverage gap, không tự suy ra app vi phạm yêu cầu chưa tồn tại.

ProRAW, linear DNG, compressed variants, pixel shift, Foveon và X-Trans chỉ được gọi
đúng subtype khi có bằng chứng metadata/decoder. Không suy ra RAF nào cũng X-Trans.
"Màu phong cách Fuji" và "nhập RAW từ máy Fuji" là hai yêu cầu khác nhau.

## 3. Tìm, lấy và cố định dữ liệu

### 3.1. Research registry

Mỗi nguồn ghi: landing URL, chính chủ, file manifest/listing nếu có, điều khoản, ngày
truy cập, quyền dùng nội bộ và chia sẻ derivative, quyết định ACCEPT/PENDING/REJECT.
Mỗi file có license evidence riêng hoặc liên kết rõ tới điều khoản bao phủ file đó.

Nguồn ưu tiên là mẫu CC0 đã xác minh trên raw.pixls.us. Kho còn có các mẫu không CC0;
không gán CC0 cho toàn bộ. Nó không nhận ảnh người/color target và không nhắm tới chuỗi
ISO/ánh sáng, nên coverage chất lượng đời thực phải được ghi trung thực. [S05]

FiveK có các điều khoản theo tập file và trang gốc nói tới sử dụng nghiên cứu. Trong
lần soạn này chưa xác minh đầy đủ các văn bản license từ máy chủ gốc. Vì vậy để nguồn
này PENDING_LICENSE_REVIEW, không tải mặc định cho R&D sản phẩm. Bản retouch chuyên gia
nếu sau này được phép dùng cũng là kết quả thẩm mỹ, không phải màu thật của cảnh. [S06]

Có thể tìm nguồn bổ sung từ tác giả/đơn vị công bố khác. Không đồng nhất "publicly
accessible", "free download", license của code downloader và quyền sử dụng ảnh.
Không bypass login, paywall, CAPTCHA hoặc chống scrape. Không dùng ảnh private của
người dùng ở bên ngoài môi trường đã cho phép. Review quyền riêng tư khi có người.

### 3.2. Manifest và an toàn

Lưu dữ liệu theo SHA-256 và extension giữ lại để thuận tiện. SHA-256 tính lần đầu chỉ
định danh byte đã tải, không tự chứng minh tính xác thực của publisher. Giữ checksum
của publisher nếu họ có, kèm thuật toán và kết quả so sánh.

Cần source URL, author/license attribution, byte count, timestamp, MIME sniff/probe,
metadata, scene tags + nguồn/độ tin cậy, split/group, camera scope và status. Thiếu dữ
liệu dùng null/unknown. Không điền camera/illuminant từ trí nhớ hoặc ảnh render để tạo
"ground truth". Không ghi GPS/serial vào HTML công khai.

Trước tải, validate domain/protocol/path; chỉ nguồn web đã duyệt, không URL trỏ localhost,
private-network, file:// hoặc redirect sang nguồn chưa duyệt. Tải .part, giới hạn byte
stream, verify rồi atomic rename. Retry tối đa 2, có backoff; 429 tuân Retry-After trong
budget. Không nối filename remote vào shell. Không giải nén archive không giới hạn.

RAW gốc bất biến, offline cache có manifest. Một working copy riêng cho từng job tránh
XMP/PP3 lẫn nhau. Symlink/hardlink không dùng khi chưa chứng minh converter không sửa
nguồn. Ghi mọi file sidecar phát sinh, không xóa file người dùng ngoài workspace.

### 3.3. Chọn mẫu và coverage

Ưu tiên một số scene khác nhau trên camera scope hơn rất nhiều hãng mỗi hãng một ảnh.
Nhắm tới Bayer/X-Trans nếu relevant; daylight, highlight, shadow, fine detail, low-light,
indoor/mixed và portrait khi có quyền. Có thể nhiều tag trên một ảnh; tổng tag không
bằng số file. ISO cao không tự chứng minh cảnh night hoặc có cặp noise reference.

Giữ các mẫu khó/failed trong bảng, không thay chúng bằng mẫu dễ để làm tỷ lệ đẹp hơn.
Trước holdout: khóa source hashes, scene split, binary/config/profile hashes, policy,
metric implementation. Agent tự làm toàn quy trình không phải đánh giá độc lập mù;
freeze và record giảm thiên lệch nhưng không loại bỏ nó. Holdout đã dùng sửa engine
phải đổi nhãn thành regression và chuẩn bị holdout mới trước kết luận xác nhận.

## 4. Khóa môi trường và adapter

### 4.1. Hợp đồng job

```text
Input: raw path/hash + engine lock + effective settings + output destination
Output: status + argv + return code + stdout/stderr + timings + artifacts + descriptors
```

Mỗi job có ID duy nhất. Resume cache key gồm source SHA, binary/build/dependency,
recipe/XMP/PP3, camera/output profiles, mode, dimensions, normalizer và metric version.
Không lấy cache result của job khác dựa vào tên file. Một job timeout không tự biến
thành unsupported; retry lỗi hạ tầng giới hạn, giữ log từng attempt.

Không dùng sudo, sửa hệ thống, Docker daemon hoặc Mac security settings nếu chưa có
quyền. Dùng user install/portable hoặc môi trường đã cấp phép. Windows/macOS/Linux
đều là khả năng, không ép Linux nếu host đã chạy đủ ba CLI. Không so tốc độ Windows
native với converter chạy trong VM rồi kết luận engine này nhanh hơn.

Các CLI là executable benchmark bên ngoài. Ghi license của bản phân phối và asset,
không copy/link code của hai dự án vào core hoặc đóng gói lại cho app ở nhiệm vụ này.
Hai dự án công bố GPL; đây không phải chỉ dẫn bỏ qua nghĩa vụ khi phân phối. [S07]

### 4.2. darktable adapter

CLI có thể chạy không GUI, nhận processing history từ XMP và cấu hình export. Không
đưa đường dẫn RAW vào GUI executable rồi giả định batch đã chạy. Dùng help của bản
cài để xác thực ICC option và TIFF bit depth; version/hash là bắt buộc. [S01]

Template minh họa, **chưa phải lệnh đã chạy**:

```sh
darktable-cli "<raw_copy>" "<validated_history.xmp>" "<output.tif>" \
  --icc-type "<supported_srgb_type>" \
  --core --conf plugins/imageio/format/tiff/bpp=16
```

Thêm config/cache/database riêng; cố định CPU/OpenCL và thread budget theo adapter.
Tùy chọn core và thư mục phải được kiểm tra trên bản cài, không ảnh hưởng database
người dùng. darktable có cơ chế cấu hình riêng và tùy chọn tắt OpenCL. [S02]

XMP/module parameters phải sinh theo format đúng version từ nguồn/fixture/template
đã kiểm chứng. Không bịa blob serialized. Lưu effective processing history từng camera
hoặc file. Nếu config không cho biết module thực sự áp dụng, đánh INDETERMINATE.
Không đủ điều kiện headless tạo XMP thì dùng default riêng và ghi BASE_BLOCKED, không
nhận default là BASE. Phải chủ động thử cách hợp lệ trước khi báo blocker.

### 4.3. RawTherapee adapter

Dùng PP3 explicit; profile layer, sidecar và default phải được cô lập. CLI có lựa chọn
TIFF/bit depth; đầu vào sau `-c` là phần cuối. Tránh overwrite và fast-export trong
nhánh chất lượng. Kiểm tra options trên build thực, không tự thêm flags. [S03]

```sh
rawtherapee-cli -o "<output.tif>" -p "<validated_base.pp3>" -t -b16 -c "<raw_copy>"
```

Đừng thêm `-d`, `-s` hoặc `-S` chỉ vì một ví dụ trên mạng có chúng: chúng thay cách
lấy processing parameters. PP3 gắn với version/schema cần được khóa; output mang đuôi
TIFF chưa đủ bằng chứng dữ liệu 16-bit. [S03, S04]

### 4.4. Adapter engine dự án

Đi qua CLI/C ABI production, dùng recipe schema thực, không viết một developer riêng
trong Python để tạo ảnh mang tên "ours". Baseline EV=0, WB as-shot resolved, identity/bypass
look; lưu source/recipe/build/profile hashes và tất cả auto adjustments.

Nếu cần diagnostic output, thêm điểm xuất từ buffer thực nhưng không thay màu trong
lần baseline đầu. Có cả diagnostic trước nén và JPEG nếu app xuất JPEG. Bản P0 từng
qua integer có headroom giới hạn; chuyển thành float không khôi phục dữ liệu đã clip.
Đối chiếu `docs/03_color_pipeline.md` và hợp đồng BufferDescriptor của dự án.

## 5. Ma trận effective settings

Agent phải điền giá trị cụ thể cho từng engine; `off`, `on`, `required`, `not_available`,
`unknown` là khác nhau. Mỗi setting cần nguồn xác minh và hash artifact.

| Nhóm | BASE_CONTROLLED yêu cầu |
|---|---|
| Input | Cùng byte RAW; không preview JPEG; ghi active area/CFA |
| Demosaic | Thuật toán thực tế, chất lượng đầy đủ; không yêu cầu các engine giống nhau |
| Black/white/calibration | Giữ xử lý cần thiết, ghi metadata và override |
| WB | Chính sách as-shot; ghi resolver/gains nếu lấy được; không Kelvin-match tùy tiện |
| Exposure/auto | EV=0 theo từng engine; ghi mọi bù exposure tự động/baseline exposure còn lại |
| Tone/gamut | Ghi module/cấu hình, không chỉ nói "neutral" |
| Profile | Camera input và output transforms hợp lệ; ID/hash/nội dung thực |
| Sharpen/NR/local contrast | Tắt tùy chọn khi hỗ trợ; ghi xử lý bắt buộc hoặc không tắt được |
| Lens/geometry | Tắt correction tùy chọn nếu được; ghi bắt buộc để biết độ so sánh |
| Creative look/film LUT/grain | Tắt; identity trên ours khi cần kiểm tra plumbing |
| Output | Full resolution, lossless >=16-bit hoặc float, màu được khai báo |
| Runtime | Bản cố định; CPU/GPU/thread count/cache condition được ghi |

Các giá trị trùng tên không có nghĩa cùng ngữ nghĩa. Cùng "EV=0" có thể có mức sáng
nền khác nhau. Không cân bằng histogram/color mỗi ảnh để xóa khác biệt đó.

Trên 2–3 fixture pilot, chạy **config-effect test**: đổi một tham số có tác động rõ và
kiểm tra output thay đổi đúng loại tác động, rồi trả lại hash baseline. Log ghi đường
dẫn XMP/PP3 chưa chứng minh tham số được dùng. Giữ artifact cho bước này, không trộn
vào bộ ảnh đánh giá chính.

## 6. Màu, hình học và normalization

### 6.1. Hai bản ảnh luôn cùng tồn tại

1. **Native export** nguyên xuất từ engine, có profile/descriptor và hash.
2. **Comparison image** sau chuyển màu/geometry được khai báo, có hash riêng.

Không ép ba native export về cùng pixel trước khi lưu. Chuyển về một output sRGB
tham chiếu có version/hash bằng CMS đã kiểm tra; không gắn profile mới mà không
transform. RawTherapee phân biệt input/working/output profiles và các TRC, nên tên
"sRGB" trên menu không thay thế việc kiểm tra file thực. [S09]

Giữ >=16-bit/float trên đường đo. Dùng thư viện/CMS hỗ trợ dtype thực tế, kiểm tra bằng
ramp tổng hợp để bắt downcast 8-bit. Không mặc định `Pillow RGB` bảo toàn TIFF16 RGB.
PNG8 cho browser chỉ là derivative hiển thị, không làm nguồn tính metric.

Không có profile thì chỉ suy luận màu khi có hợp đồng verified rõ, ghi `assumed_from_verified_contract`;
không đủ bằng chứng thì block metric màu. Không âm thầm clamp NaN/Inf/negative/high
values trước kiểm tra. Mức âm hoặc >1 có thể hợp lệ ở domain float unbounded; chỉ fail
nếu vi phạm range policy của chính buffer.

### 6.2. Geometry

Normalize orientation đúng một lần theo metadata/hợp đồng; kích thước khác không tự
là lỗi vì active area/crop/lens correction khác. Ghi frame gốc và active rectangle.
So pixel chỉ khi ánh xạ có bằng chứng: integer translation/crop nếu phù hợp, cùng scale,
không auto warp để giấu khác biệt. Lưu transform và overlap mask. Không align được:
`NOT_COMPARABLE` cho pixel metric, vẫn giữ full-frame/crop riêng để xem.

Global resize chỉ tạo thumbnail/overview. Không dùng resized image để nói demosaic
kém. Crop chi tiết trên grid gốc; UI hiển thị rõ 100% nghĩa 1 source pixel/1 CSS pixel
ở zoom trình duyệt 100%, kèm nút native crop để kiểm tra trên màn hình thực tế.

### 6.3. Luminance matching

Kết quả chính tuyệt đối không tự WB-match, histogram-match, fit tone curve hoặc
per-channel scale theo reference. Có thể thêm nhánh `EXPOSURE_MATCHED_DIAGNOSTIC`
với một scalar global trong linear RGB trên ROI đã khóa, lưu hệ số/mask. Nhánh này
chỉ phân tích phụ, không thay native output hoặc xóa cảnh báo độ sáng.

## 7. Số đo và cách diễn giải

### 7.1. Hard checks — có thể PASS/FAIL khách quan

- Source hash trước/sau; source bytes dùng bởi ba engine trùng nhau.
- Exit code và artifact thực: đọc được, kích thước không rỗng, checksum hợp lệ.
- Output dtype/ICC/descriptor nhất quán với hợp đồng; không giả TIFF16 từ JPEG8.
- Không có NaN/Inf; đúng orientation/geometry theo oracle metadata đã xác minh.
- Cùng engine/build/recipe/context lặp lại, so pre-JPEG theo budget của engine.
- Config effect và resume invalidation đúng.
- Failure không bị report bỏ sót; status counts có mẫu số planned rõ.

Hard check thất bại ở normalizer/profile adapter không tự kết luận core bug. Gán owner:
`engine`, `converter_config`, `harness`, `input`, `environment` hoặc `undetermined`.

### 7.2. Heuristics — chỉ để chọn ảnh cần xem

Policy đính kèm là ngưỡng thăm dò, **không phải chuẩn chất lượng**. Khóa trước holdout.
Không dùng một score tổng để chấm engine.

| Metric | Định nghĩa/điều kiện |
|---|---|
| Near-white | Trong encoded SDR sRGB: tỷ lệ max(R,G,B)>=0.995, thêm tỷ lệ min>=0.995; dùng cùng overlap mask |
| Near-black | Tỷ lệ max(R,G,B)<=0.005, thêm tỷ lệ theo từng kênh; cùng domain/mask |
| Endpoint difference | Chênh so từng reference; flag nếu lớn hơn cả hai >=0.02 (=2 điểm phần trăm) |
| Luminance | `Y=0.2126R+0.7152G+0.0722B` sau decode sRGB đúng; quantiles p1/p50/p99 |
| Brightness disparity | `abs(log2(medianY_a/medianY_b))>=0.5` khi cả medianY>0.01; không diễn giải thành exposure RAW bị sai |
| Pixel diff | MAE/RMSE, heatmap với scale cố định khi color/geometry comparable; không pass/fail cross-engine |
| Detail/chroma proxy | Chỉ ở ROI phù hợp và cùng scale/tone context; formula phải khóa; xem crop để kiểm chứng |

Hai dòng đầu là **tỷ lệ gần đầu mút output**, không chứng minh sensor clipping hoặc
số stop recover. Một vùng trời trắng hợp lệ có thể bị flag. Engine đen toàn bộ có tỷ
lệ trắng 0 nhưng không phải tốt hơn. Các kết quả kênh cao do màu bão hòa cũng cần phân biệt.
Một rule chỉ dùng khi đủ hai reference hợp lệ; thiếu reference thì ghi PARTIAL_REFERENCE,
không tự thay reference vắng bằng số 0. So sánh pairwise vẫn có thể hiển thị riêng.

Với noise: một ảnh tự nhiên có texture không cho ground-truth noise. ROI phẳng tự động
chọn là `candidate`, không phải vùng phẳng đã biết. Có thể dùng residual/MAD/high-frequency
chroma làm proxy nhưng phải công bố mẫu ROI và điều kiện; không kết luận sensor SNR.
Tương tự, gradient/Laplacian lớn có thể do sharpen/noise, không mặc định nhiều chi tiết tốt.

Global mean RGB của ảnh cây xanh không phải phép đo green cast. Chỉ đánh neutrality với
ROI trung tính có căn cứ, WB/illuminant phù hợp; trường hợp còn lại gọi là color difference.
Đánh false color/moire cần crop và người/tiêu chí xác minh; một chỉ số high-frequency không
đủ xác nhận lỗi. SSIM/PSNR/Delta E nếu bổ sung chỉ là mô tả sai khác, không ground truth.

### 7.3. Controlled tests bổ sung, có điều kiện

Chart accuracy chỉ chạy khi có RAW chart thật, ROI, reference phản xạ/màu của chart và
điều kiện chiếu sáng/white reference đủ rõ. Ghi illuminant, observer, adaptation, exposure
normalization, reference provenance và chart wear/measurement limitation. Không dùng bảng
Lab D50 rồi so thẳng với Lab D65, hoặc coi đèn "5500K" là phổ D55 chuẩn. Thiếu dữ liệu:
`NOT_RUN: NO_VALID_COLOR_REFERENCE`, không chặn differential benchmark.

Exposure `x*2^EV` chỉ được unit/integration-test quanh đúng stage tuyến tính theo contract,
trước tone/clamp không liên quan. Không yêu cầu JPEG sau tone tăng đúng gấp đôi. Không
đòi WB gain custom tạo một tỷ lệ RGB cuối cố định khi còn matrix/tone.

Dynamic range và phục hồi highlight: cần phân biệt sensor saturation với downstream
clipping, và có dữ liệu bracket/black-white calibration phù hợp. Public single-shot corpus
không đủ để tự công bố số stop hoặc màu thật của cảnh.

## 8. Kiểm thử chính harness

Không dùng ảnh engine tự render để sinh expected cho chính phép đo đang test. Dùng ma
trận/synthetic arrays có đáp án biết trước; phần tổng hợp được đánh nhãn riêng, không
trộn vào số lượng RAW corpus.

| ID | Dữ liệu/tình huống | Expected bắt buộc |
|---|---|---|
| H01 | Hai array giống nhau | Diff=0, descriptor/mask thống nhất |
| H02 | Đổi một pixel/kênh đã biết | MAE/RMSE/max khớp tính tay |
| H03 | 10/100 pixel gần trắng | Endpoint fraction=0.10, không 10 hoặc 0.01 |
| H04 | Shift 1px; orientation EXIF xoay | Phát hiện mapping hoặc NOT_COMPARABLE; không metric sai trên frame lệch |
| H05 | Ramp16 nhiều hơn 256 mức | Không bị hạ ngầm xuống 8-bit khi normalize |
| H06 | NaN/Inf, float >1 ở 2 domain | Nonfinite fail; >1 chỉ fail ở domain cấm, không fail unbounded mặc định |
| H07 | Missing/wrong ICC so với verified descriptor | Reject/flag inconsistency; không tự gắn sRGB rồi pass |
| H08 | Process exit=0 nhưng thiếu/truncated output | Job không SUCCESS; report vẫn có row |
| H09 | Process treo/exit lỗi/unsupported | Timeout/status riêng; dọn process thuộc job, giữ log |
| H10 | Đổi config/source/binary, cùng filename | Cache invalidated; không dùng ảnh cũ |
| H11 | Download thiếu header/quá quota/hash sai | Dừng an toàn; file .part không vào corpus |
| H12 | Một reference fail; một ảnh portrait không có | Không metric giả, không coverage PASS; denominator planned còn nguyên |
| H13 | Bỏ qua PP3/XMP trong adapter thử | Config-effect test bắt được; không chỉ so argv |
| H14 | 100% output đen hoặc trắng | Technical anomaly/review; không được "best clipping score" |

Không đánh giá visual thật khi agent không có công cụ xem ảnh. Báo `NOT_VISUALLY_REVIEWED`
và tạo report để người dùng kiểm tra, thay vì tự mô tả màu đẹp từ histogram.

## 9. Hiệu năng: ghi đúng thứ đã đo

Mỗi job đo wall time và trạng thái cache; thêm peak RSS/process-tree nếu phương pháp đo
hỗ trợ. Ghi metric/sampling/OS; sampling peak không phải peak tuyệt đối. Không lấy memory
của runner Python làm memory của subprocess. Không so hiệu năng của ba pipeline không
cùng chức năng để xếp hạng engine tối ưu.

V1: chạy một lượt full corpus; thêm 3 fresh-process render/engine trên 3 mẫu pilot cố định
để quan sát độ biến động. "Fresh process" không phải cold disk/OS cache. Không dùng n=3
để công bố p95 tin cậy. Trên mỗi fixture có n, các số đo, median và range.

R-04 đầy đủ 30 warm/5 cold trên thiết bị theo tài liệu cũ là bước riêng, không bắt vòng
này phải hoàn thành và không suy desktop sang mobile. Cache hit của runner ghi riêng,
không có render duration giả.

## 10. Report và blind review

### 10.1. Trang tổng quan

Số planned RAW × engine × mode; số fetched, attempted, successful, failed, unsupported,
blocked, not-run; số cặp comparable/not-comparable. Hiển thị coverage camera/CFA/scene/split,
license pending, số mẫu thiếu. Không gọi 100% khi chỉ hoàn thành 20 trong kế hoạch 40.

Tách panel **execution**, **technical checks**, **quality triage**, **human review**.
Không dùng biểu tượng PASS của render thay cho chất lượng hình ảnh.

### 10.2. Trang từng ảnh

Native export và normalized overview, config summary, thông tin ảnh đã rút dữ liệu nhạy
cảm, ảnh crop theo ROI/mapping, histogram, endpoint masks, metric domain/unit và diff scale.
Không dùng auto-contrast riêng mỗi heatmap khiến sai số bé trông như lớn. Thumbnail là
preview, có đường dẫn ảnh/crop full-quality. Các file lỗi có log và nguyên nhân, không
biến mất khỏi gallery.

HTML tự chứa assets hoặc relative local assets, không CDN/font tải ngoài; escape metadata
và tên file để tránh HTML injection. Nếu browser file:// hạn chế, cung cấp tùy chọn
localhost server chỉ bind 127.0.0.1, không tự mở ra LAN/internet.

### 10.3. Blind review tùy chọn

Trang A/B/C random thứ tự theo seed/mỗi scene. Mapping không hiện trong title/filename UI,
không tự tuyên bố double-blind; người mở source có thể thấy mapping nếu thiết kế không tách.
Lưu phiếu feedback hoặc JSON tải về, có ID người review/scene/seed mà không cần tài khoản.

Xem tất cả flagged và một mẫu deterministic ít nhất 20% non-flagged để kiểm tra false
negative. Review tập trung highlight, chi tiết/artifact, màu da nếu có scene thích hợp;
phân biệt sở thích với lỗi. Không có reviewer thì `NOT_REVIEWED`; đánh giá của vision agent
phải nhãn `AI_SUGGESTION`, không thay phiếu người dùng hoặc ground truth.

## 11. Trạng thái và điều kiện bàn giao

Job: `SUCCESS | FAILED | UNSUPPORTED | TIMEOUT | BLOCKED | NOT_RUN`.
Technical test: `PASS | FAIL | BLOCKED | NOT_RUN | NOT_APPLICABLE`.
Comparison: `COMPARABLE | NOT_COMPARABLE | PARTIAL_REFERENCE`.
Quality triage: `NO_FLAG | REVIEW_REQUIRED | NOT_EVALUATED`.
Human review: `NOT_REVIEWED | ACCEPTABLE_FOR_SCOPE | ISSUE_CONFIRMED | INCONCLUSIVE`.

Runner status:
- `COMPLETE`: đã thực hiện toàn bộ planned actions có áp dụng; có thể vẫn có FAIL.
- `PARTIAL`: còn action BLOCKED/NOT_RUN hoặc chưa đủ corpus; nêu rõ.
- `INVALID`: pipeline cấu hình/normalization/provenance không đủ tin cậy cho kết luận.

`ready_for_G2_review` chỉ là boolean đề nghị review, không là nghiệm thu. Phải có cấu
hình tin cậy, scope/corpus rõ, report đủ, không unresolved hard failure trên required
scope; quality anomalies/coverage gaps liệt kê để người duyệt quyết định. Không tự nâng
camera từ experimental thành certified. Chưa có chart thì kết luận độ chính xác màu
vật lý vẫn unassessed dù differential report đầy đủ.

Deliverables tối thiểu: source runner/adapters/tests; README; policy lock; source registry;
corpus manifest; engine locks; XMP/PP3/recipe; original+normalized artifacts; per-job logs;
metrics JSON/CSV; offline report; list issues+owner+repro; one-page final report.

## 12. Thứ tự triển khai để không sa đà

A. Inspect repo và lưu baseline trạng thái hiện tại.
B. Adapter ours + darktable + RawTherapee, 1 RAW qua đủ ba, kiểm tra color/geometry thật.
C. Test harness, config-effect, source license/manifest và pilot 12.
D. Khóa policy/config/split, mở rộng tới 40 trong budget, chạy holdout sau khóa.
E. Generate HTML, triage, top issues và đọc lại các result counts từ artifact.
F. Chỉ sau đó đề xuất sửa core hoặc chuyển sang controlled chart/preset work.

Không bắt buộc hoàn thành mọi nghiên cứu phụ trước khi tạo report pilot. Không gọi việc
viết được runner hoặc synthetic PASS là đã chạy benchmark ảnh thật.
