create or alter VIEW [dbo].[BQ_Group_Incremental] AS
SELECT
    g.Id,
    CASE WHEN g.IsSystem = 1 THEN 'true' WHEN g.IsSystem = 0 THEN 'false' ELSE NULL END AS IsSystem,
    g.ParentGroupId,
    g.GroupTypeId,
    g.CampusId,
    g.Name,
    g.Description,
    CASE WHEN g.IsSecurityRole = 1 THEN 'true' WHEN g.IsSecurityRole = 0 THEN 'false' ELSE NULL END AS IsSecurityRole,
    CASE WHEN g.IsActive = 1 THEN 'true' WHEN g.IsActive = 0 THEN 'false' ELSE NULL END AS IsActive,
    g.[Order],
    CAST(g.Guid AS nvarchar(36)) AS Guid,
    CONVERT(varchar(19), g.CreatedDateTime, 120) AS CreatedDateTime,
    CONVERT(varchar(19), g.ModifiedDateTime, 120) AS ModifiedDateTime,
    g.CreatedByPersonAliasId,
    g.ModifiedByPersonAliasId,
    g.ForeignKey,
    CASE WHEN g.AllowGuests = 1 THEN 'true' WHEN g.AllowGuests = 0 THEN 'false' ELSE NULL END AS AllowGuests,
    g.ScheduleId,
    CASE WHEN g.IsPublic = 1 THEN 'true' WHEN g.IsPublic = 0 THEN 'false' ELSE NULL END AS IsPublic,
    CAST(g.ForeignGuid AS nvarchar(36)) AS ForeignGuid,
    g.ForeignId,
    g.GroupCapacity,
    g.RequiredSignatureDocumentTemplateId,
    CONVERT(varchar(19), g.InactiveDateTime, 120) AS InactiveDateTime,
    CASE WHEN g.IsArchived = 1 THEN 'true' WHEN g.IsArchived = 0 THEN 'false' ELSE NULL END AS IsArchived,
    CONVERT(varchar(19), g.ArchivedDateTime, 120) AS ArchivedDateTime,
    g.ArchivedByPersonAliasId,
    g.StatusValueId,
    g.GroupAdministratorPersonAliasId,
    CASE WHEN g.SchedulingMustMeetRequirements = 1 THEN 'true' WHEN g.SchedulingMustMeetRequirements = 0 THEN 'false' ELSE NULL END AS SchedulingMustMeetRequirements,
    g.AttendanceRecordRequiredForCheckIn,
    g.ScheduleCoordinatorPersonAliasId,
    CAST(g.InactiveReasonValueId AS nvarchar(20)) AS InactiveReasonValueId,
    g.InactiveReasonNote,
    g.RSVPReminderSystemCommunicationId,
    g.RSVPReminderOffsetDays,
    CASE WHEN g.DisableScheduleToolboxAccess = 1 THEN 'true' WHEN g.DisableScheduleToolboxAccess = 0 THEN 'false' ELSE NULL END AS DisableScheduleToolboxAccess,
    CASE WHEN g.DisableScheduling = 1 THEN 'true' WHEN g.DisableScheduling = 0 THEN 'false' ELSE NULL END AS DisableScheduling,
    g.GroupSalutation,
    g.GroupSalutationFull,
    g.ElevatedSecurityLevel,
    g.ConfirmationAdditionalDetails,
    CAST(g.ReminderSystemCommunicationId AS nvarchar(20)) AS ReminderSystemCommunicationId,
    CAST(g.ReminderOffsetDays AS nvarchar(20)) AS ReminderOffsetDays,
    g.ReminderAdditionalDetails,
    g.ScheduleConfirmationLogic,
    CASE WHEN g.RelationshipGrowthEnabledOverride = 1 THEN 'true' WHEN g.RelationshipGrowthEnabledOverride = 0 THEN 'false' ELSE NULL END AS RelationshipGrowthEnabledOverride,
    CAST(g.RelationshipStrengthOverride AS nvarchar(20)) AS RelationshipStrengthOverride,
    CAST(g.LeaderToLeaderRelationshipMultiplierOverride AS nvarchar(40)) AS LeaderToLeaderRelationshipMultiplierOverride,
    CAST(g.LeaderToNonLeaderRelationshipMultiplierOverride AS nvarchar(40)) AS LeaderToNonLeaderRelationshipMultiplierOverride,
    CAST(g.NonLeaderToNonLeaderRelationshipMultiplierOverride AS nvarchar(40)) AS NonLeaderToNonLeaderRelationshipMultiplierOverride,
    CAST(g.NonLeaderToLeaderRelationshipMultiplierOverride AS nvarchar(40)) AS NonLeaderToLeaderRelationshipMultiplierOverride,
    CASE WHEN g.IsSpecialNeeds = 1 THEN 'true' WHEN g.IsSpecialNeeds = 0 THEN 'false' ELSE NULL END AS IsSpecialNeeds,
    g.ScheduleCoordinatorNotificationTypes,
    CASE WHEN g.IsChatEnabledOverride = 1 THEN 'true' WHEN g.IsChatEnabledOverride = 0 THEN 'false' ELSE NULL END AS IsChatEnabledOverride,
    CASE WHEN g.IsLeavingChatChannelAllowedOverride = 1 THEN 'true' WHEN g.IsLeavingChatChannelAllowedOverride = 0 THEN 'false' ELSE NULL END AS IsLeavingChatChannelAllowedOverride,
    CASE WHEN g.IsChatChannelPublicOverride = 1 THEN 'true' WHEN g.IsChatChannelPublicOverride = 0 THEN 'false' ELSE NULL END AS IsChatChannelPublicOverride,
    CASE WHEN g.IsChatChannelAlwaysShownOverride = 1 THEN 'true' WHEN g.IsChatChannelAlwaysShownOverride = 0 THEN 'false' ELSE NULL END AS IsChatChannelAlwaysShownOverride,
    g.ChatChannelKey,
    CAST(g.GroupMemberRecordSourceValueId AS nvarchar(20)) AS GroupMemberRecordSourceValueId,
    CAST(g.ChatChannelAvatarBinaryFileId AS nvarchar(20)) AS ChatChannelAvatarBinaryFileId,
    CAST(g.ChatPushNotificationModeOverride AS nvarchar(20)) AS ChatPushNotificationModeOverride,
    CONVERT(varchar(19), CURRENT_TIMESTAMP, 120) AS _loaded_at,
    'rock_rms' AS _source_system
FROM [Group] g
WHERE g.ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Group_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND g.ModifiedDateTime <= CURRENT_TIMESTAMP;

-- select column_name, data_type
-- from information_schema.columns
-- where table_name = 'BQ_Group_Incremental'