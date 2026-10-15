CREATE OR ALTER VIEW dbo.BQ_Person_ATX_Historical_Incremental AS
WITH ranked AS (
    SELECT 
        h.Id,
        h.PersonId,
        h.CurrentRowIndicator,
        h.EffectiveDate,
        h.ExpireDate,
        h.PrimaryFamilyId,
        h.RecordTypeValueId,
        h.RecordStatusValueId,
        h.RecordStatusLastModifiedDateTime,
        h.RecordStatusReasonValueId,
        h.ConnectionStatusValueId,
        h.ReviewReasonValueId,
        h.IsDeceased,
        h.TitleValueId,
        h.FirstName,
        h.NickName,
        h.MiddleName,
        h.LastName,
        h.SuffixValueId,
        h.PhotoId,
        h.BirthDay,
        h.BirthMonth,
        h.BirthYear,
        h.BirthDateKey,
        h.Age,
        h.Gender,
        h.MaritalStatusValueId,
        h.AnniversaryDate,
        h.GraduationYear,
        h.GivingGroupId,
        h.GivingId,
        h.GivingLeaderId,
        h.Email,
        h.EmailPreference,
        h.ReviewReasonNote,
        h.InactiveReasonNote,
        h.SystemNote,
        h.ViewedCount,
        CAST(h.Guid AS NVARCHAR(36))                              AS Guid,
        h.ForeignId,
        CAST(h.ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
        h.ForeignKey,
        h.Count,
        h.core_CurrentlyAnEra,
        h.core_EraStartDate,
        h.core_EraFirstGave,
        h.core_EraLastGave,
        CAST(h.core_TimesCheckedIn16Wks AS FLOAT)                 AS core_TimesCheckedIn16Wks,
        CAST(h.core_EraTimesGiven52Wks AS FLOAT)                  AS core_EraTimesGiven52Wks,
        CAST(h.core_EraTimesGiven6Wks AS FLOAT)                   AS core_EraTimesGiven6Wks,
        h.CurrentJourneyGivingStage,
        h.FrequencyLabel,
        CAST(h.GiftAmountIQR AS FLOAT)                            AS GiftAmountIQR,
        CAST(h.GiftAmountMedian AS FLOAT)                         AS GiftAmountMedian,
        CAST(h.GiftFrequencyDaysMean AS FLOAT)                    AS GiftFrequencyDaysMean,
        CAST(h.GiftFrequencyDaysStandardDeviation AS FLOAT)       AS GiftFrequencyDaysStandardDeviation,
        CAST(h.GivingBin AS FLOAT)                                AS GivingBin,
        CAST(h.GivingPercentile AS FLOAT)                         AS GivingPercentile,
        h.LastClassificationRunDateTime,
        h.NextExpectedGiftDate,
        h.PreferredCurrency,
        h.PreviousJourneyGivingStage,
        h.JourneyGivingStageChangeDate,
        h.DonorFundsOrganization,
        h.MaritalStatus,
        h.ConnectionStatus,
        h.ReviewReason,
        h.RecordStatus,
        h.RecordStatusReason,
        h.RecordType,
        h.Suffix,
        h.Title,
        h.GenderText,
        h.EmailPreferenceText,
        h.CampusId,
        h.CampusName,
        h.CampusShortCode,
        h.PrimaryFamilyKey,
        h.MailingAddressStreet1,
        h.MailingAddressStreet2,
        h.MailingAddressCity,
        h.MailingAddressCounty,
        h.MailingAddressState,
        h.MailingAddressCountry,
        h.MailingAddressPostalCode,
        h.MailingAddressLatitude,
        h.MailingAddressLongitude,
        h.MailingAddressFull,
        h.MappedAddressStreet1,
        h.MappedAddressStreet2,
        h.MappedAddressCity,
        h.MappedAddressCounty,
        h.MappedAddressState,
        h.MappedAddressCountry,
        h.MappedAddressPostalCode,
        h.MappedAddressLatitude,
        h.MappedAddressLongitude,
        h.MappedAddressFull,
        ROW_NUMBER() OVER (
            PARTITION BY h.PersonId
            ORDER BY h.EffectiveDate DESC, h.Id DESC
        ) AS rn
    FROM dbo.AnalyticsDimPersonHistorical h
),
recent_people AS (
    -- anyone whose newest row was created in the lookback window, for
    -- whatever reason (identity change, status change, giving
    -- reclassification -- doesn't matter, a new row is a new row)
    SELECT PersonId
    FROM ranked
    WHERE rn = 1
      AND EffectiveDate >= DATEADD(HOUR, -26, GETUTCDATE())
)
SELECT
    ranked.*,
    GETUTCDATE()                                                  AS _loaded_at,
    'rock_rms'                                                     AS _source_system
FROM ranked
INNER JOIN recent_people rp ON rp.PersonId = ranked.PersonId
WHERE ranked.rn <= 2


-- select * from dbo.BQ_Person_ATX_Historical_Incremental