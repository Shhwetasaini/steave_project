from flask import Blueprint
from app.views.authentication import *
from app.views.messaging import *
from app.views.seller_add_property import *
from app.views.media import *
from app.views.properties import *
from app.views.admin.documents import *
from app.views.admin.messaging import *
from app.views.admin.users import *
from app.views.admin.context_processors import *
from app.views.pre_qualified import *
from app.views.id_verification import *
from app.views.saved_searches import *

api_bp = Blueprint('api', __name__, url_prefix='/api')

api_bp.add_url_rule(rule='/user/register', view_func=RegisterUserView.as_view('register'))
api_bp.add_url_rule(rule='/user/uuid', view_func=UserUUIDView.as_view('user_uuid'))
api_bp.add_url_rule(rule='/user/verify-otp', view_func=VerifyOtpView.as_view('verify_otp'))
api_bp.add_url_rule(rule='/user/login', view_func=LoginUserView.as_view('login'))
api_bp.add_url_rule(rule='/user/validate_token', view_func=ValidateTokenView.as_view('validate_token'))
api_bp.add_url_rule(rule='/user/refresh_token', view_func=RefreshTokenView.as_view('refresh_token')) #token refresh
api_bp.add_url_rule(rule='/user/signin', view_func=UserUuidLoginView.as_view('signin')) #for uuid login
api_bp.add_url_rule(rule='/user/profile', view_func=ProfileUserView.as_view('profile'))
api_bp.add_url_rule(rule='/user/logout', view_func=LogoutUserView.as_view('logout'))
api_bp.add_url_rule(rule='/user/update', view_func=UpdateUsersView.as_view('update_user'))
api_bp.add_url_rule(rule='/user/forgot-passwd', view_func=ForgetPasswdView.as_view('forgot_passwd'))
api_bp.add_url_rule(rule='/user/reset-passwd', view_func=ResetPasswdView.as_view('reset_passwd'))
api_bp.add_url_rule(rule='/search-address', view_func=SearchAddressAutoCompleteView.as_view('search-address'))


api_bp.add_url_rule(rule='/user/check_response', view_func=CheckResponseView.as_view('check_response'))
api_bp.add_url_rule(rule='/user/send-message', view_func=SaveUserMessageView.as_view('send_message'))

# Users Media and documents - user documents
api_bp.add_url_rule(rule='/user-document/download', view_func=DownloadDocView.as_view('document_download_post')) #user documents
api_bp.add_url_rule(rule='/user-document/download', view_func=UserDownloadedDocsView.as_view('user_downloaded_document_get')) #user documents
api_bp.add_url_rule(rule='/user-document/filter', view_func=UserDocumentsView.as_view('user_uploaded_documents')) #user documents
api_bp.add_url_rule(rule='/user-document', view_func=UploadDocView.as_view('document_upload_post')) #user documents
api_bp.add_url_rule(rule='/user-document/<string:doc_id>', view_func=UploadDocView.as_view('document_delete_put')) #user documents

# Users Media and documents - Templates
api_bp.add_url_rule(rule='/template-docs', view_func=AllDocsView.as_view('docs')) #templates
api_bp.add_url_rule(rule='/template-docs/<string:document_id>', view_func=DocumentFillRequestView.as_view('docs_fill_request')) #Templates
api_bp.add_url_rule(rule='/template-docs/answer/<string:document_id>', view_func=DocAnswerInsertionView.as_view('docs_answer-get-post')) #Templates
api_bp.add_url_rule(rule='/template-docs', view_func=DocumentPrefillAnswerView.as_view('docs_prefill_answers')) #Templates

#media
api_bp.add_url_rule(rule='/media', view_func=SendMediaView.as_view('users_media')) #media
api_bp.add_url_rule(rule='/media', view_func=DeleteMediaView.as_view('users_media_delete')) #media
api_bp.add_url_rule(rule='/media', view_func=ReceiveMediaView.as_view('receivemedia')) #media

#Properties
api_bp.add_url_rule(rule='user/properties/add/property-type-selection', view_func=PropertyTypeSelectionView.as_view('property_type_selection'))
api_bp.add_url_rule(rule='user/properties/add/upload-image', view_func=PropertyUploadImageView.as_view('property_images'))
api_bp.add_url_rule(rule='user/properties/add/save-pdf', view_func=SavePdfView.as_view('save_pdf'))
api_bp.add_url_rule(rule='user/properties/add/checkout', view_func=CheckoutView.as_view('property_checkout'))
api_bp.add_url_rule(rule='user/properties/add/property-tour', view_func=PropertyTourView.as_view('property_tour'))

api_bp.add_url_rule(rule='user/properties/list', view_func=SellerPropertyListView.as_view('user_properties_list'))   #individual seller properties
api_bp.add_url_rule(rule='user/properties', view_func=AllPropertyListView.as_view('user_properties'))
api_bp.add_url_rule(rule='user/properties/<string:property_id>', view_func=UserPropertyView.as_view('user_property_view_update'))
api_bp.add_url_rule(rule='user/properties/image/remove', view_func=PropertyImageDeleteView.as_view('user_properties_image_remove'))
api_bp.add_url_rule(rule='user/properties/image/label', view_func=PropertyImageLabelUpdateView.as_view('user_properties_image_label'))
api_bp.add_url_rule(rule='user/properties/add/external', view_func=ExternalPropertyAddView.as_view('user_properties_add_external'))
api_bp.add_url_rule(rule='user/properties/panoramic_images', view_func=PanoramicImageView.as_view('user_properties_add_panoramic_images'))
api_bp.add_url_rule(rule='user/properties/panoramic_images/<string:property_id>', view_func=PanoramicImageView.as_view('user_properties_get_panoramic_images'))
api_bp.add_url_rule(rule='user/properties/panoramic_images/<string:property_id>/<int:property_version>/<int:order>', view_func=PanoramicImageView.as_view('user_properties_delete_panoramic_images'))
api_bp.add_url_rule(rule='user/properties/search', view_func=PropertySearchFilterView.as_view('user_property_search'))
api_bp.add_url_rule(rule='user/properties/mobile_search', view_func=PropertySearchFilterMobileView.as_view('user_property_mobile_search'))
api_bp.add_url_rule(rule='user/properties/favorite', view_func=FavoritePropertyView.as_view('user_property_favorite'))

# Admin UI APIs
api_bp.add_url_rule(rule='/admin/context-processor', view_func=ContextProcessorsDataView.as_view('admin_context_processor'))
api_bp.add_url_rule(rule='/admin/check-token', view_func=TokenCheckView.as_view('admin_check_token'))
api_bp.add_url_rule(rule='/admin/dashboard', view_func=DashboardView.as_view('admin_dashboard'))
api_bp.add_url_rule(rule='/admin/users', view_func=AllUserView.as_view('users'))
api_bp.add_url_rule(rule='/admin/user/register', view_func=AdminRegisterUserView.as_view('admin_user_register'))
api_bp.add_url_rule(rule='/admin/user/add', view_func=AddUserView.as_view('admin_user_add'))
api_bp.add_url_rule(rule='/admin/user/login', view_func=AdminUserLoginView.as_view('admin_user_login'))
api_bp.add_url_rule(rule='/admin/user/update', view_func=EditUsersView.as_view('admin_user_update'))
api_bp.add_url_rule(rule='/admin/user/delete', view_func=DeleteUserView.as_view('admin_user_delete'))
api_bp.add_url_rule(rule='/admin/user/media', view_func=GetMediaView.as_view('admin_user_media'))
api_bp.add_url_rule(rule='/admin/user/downloded-docs/<uuid>', view_func=DownloadedDocsView.as_view('admin_user_downloaded_docs'))
api_bp.add_url_rule(rule='/admin/user/uploaded-docs/<uuid>', view_func=UploadedDocsView.as_view('admin_user_uploaded_docs'))
api_bp.add_url_rule(rule='/admin/user/chats', view_func=UserCustomerChatUsersListView.as_view('admin_user_chats'))
api_bp.add_url_rule(rule='/admin/response', view_func=SaveAdminResponseView.as_view('admin_response'), methods=['POST'])
api_bp.add_url_rule(rule='/admin/response/<user_id>', view_func=SaveAdminResponseView.as_view('admin_response_messages'), methods=['GET'])
api_bp.add_url_rule(rule='/admin/property/response', view_func=SavePropertyAdminResponseView.as_view('admin_property_resoponse'), methods=['POST'])
api_bp.add_url_rule(rule='/admin/property/response/<property_id>/<user_id>', view_func=SavePropertyAdminResponseView.as_view('admin_property_messages'), methods=['GET'])
api_bp.add_url_rule(rule='/admin/documents', view_func=AllDocumentsView.as_view('admin_documents'))
api_bp.add_url_rule(rule='/admin/flforms', view_func=FlFormsView.as_view('admin_flforms'))
api_bp.add_url_rule(rule='/admin/mnforms', view_func=MnFormsView.as_view('admin_mnforms'))
api_bp.add_url_rule(rule='/admin/flforms/<filename>/<folder>', view_func=SingleFlFormsView.as_view('admin_flforms_single'))
api_bp.add_url_rule(rule='/admin/mnforms/<filename>/<folder>', view_func=SingleMnFormsView.as_view('admin_mnforms_single'))
api_bp.add_url_rule(rule='/admin/document/update', view_func=EditDocumentsView.as_view('admin_document_update'))
api_bp.add_url_rule(rule='/admin/document/upload', view_func=UploadDocumentView.as_view('admin_document_upload'))
api_bp.add_url_rule(rule='/admin/document/flforms/move', view_func=MoveFlFormsFileView.as_view('admin_document_flforms_move'))
api_bp.add_url_rule(rule='/admin/document/mnforms/move', view_func=MoveMnFormsFileView.as_view('admin_document_mnforms_move'))
api_bp.add_url_rule(rule='/admin/user/actions', view_func=ActionLogsView.as_view('admin_user_action'))
api_bp.add_url_rule(rule='/admin/user/property/chat/list', view_func=UserCustomerPropertyChatUsersListView.as_view('admin_user_property_chat_list'))
api_bp.add_url_rule(rule='/admin/forms/question', view_func=SingleFormQuestionView.as_view('admin_forms_question'))

# Buyers APIs
api_bp.add_url_rule(rule='/users/buyer/sellers/chat', view_func=BuyerSellersChatView.as_view('buyer_sellers_chat'), methods=['POST'])
api_bp.add_url_rule(rule='/users/buyer/sellers/chat/<property_id>/<user_id>', view_func=BuyerSellersChatView.as_view('buyer_seller_message'), methods=['GET'])
api_bp.add_url_rule(rule='/users/chat/list', view_func=BuyerSellerChatUsersListView.as_view('buyer_seller_chat_users_list'))
api_bp.add_url_rule(rule='/users/buyer/seller/chat/search', view_func=BuyerSellerChatSearchView.as_view('buyer_sellers_chat_search'))

#User-Customer-service property chat apis
api_bp.add_url_rule(rule='/users/customer/property/chat', view_func=UserCustomerServicePropertySendMesssageView.as_view('user-customer-service_chat'), methods=['POST'])
api_bp.add_url_rule(rule='/users/customer/property/chat/<property_id>', view_func=UserCustomerServicePropertySendMesssageView.as_view('user-customer-service_message'), methods=['GET'])
api_bp.add_url_rule(rule='/users/customer/property/chat/list', view_func=UserCustomerServicePropertyChatUserList.as_view('user_customer_property_chat_list'))

# Routes for fre-qualified 
api_bp.add_url_rule('/timeline_stage', view_func=PrequalView.as_view('timeline_stage'), methods=['POST'])
api_bp.add_url_rule('/home_use_type', view_func=PrequalView.as_view('home_use_type'), methods=['POST'])
api_bp.add_url_rule('/budget_payment', view_func=PrequalView.as_view('budget_payment'), methods=['POST'])
api_bp.add_url_rule('/personal_info', view_func=PrequalView.as_view('personal_info'), methods=['POST'])
api_bp.add_url_rule('/real_estate_agent', view_func=PrequalView.as_view('real_estate_agent'), methods=['POST'])
api_bp.add_url_rule('/borrower', view_func=PrequalView.as_view('co_borrower'), methods=['POST'])
api_bp.add_url_rule('/citizenship_financial_history', view_func=PrequalView.as_view('citizenship_financial_history'), methods=['POST'])
api_bp.add_url_rule('/va_first_time_homebuyer', view_func=PrequalView.as_view('va_first_time_homebuyer'), methods=['POST'])
api_bp.add_url_rule('/credit_score', view_func=PrequalView.as_view('credit_score'), methods=['POST'])

# Idverifications
api_bp.add_url_rule(rule='/id-verification',view_func=IDVerificationView.as_view('id_verification'),methods=['POST'])

#saved search 
api_bp.add_url_rule('/saved_searches', view_func=SavedSearchView.as_view('saved_searches'), methods=['GET', 'POST'])
api_bp.add_url_rule('/saved_searches/<string:search_id>', view_func=SavedSearchView.as_view('saved_search'), methods=['GET', 'PUT', 'DELETE'])